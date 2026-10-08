"""Local web UI for the downloader. Run with ./run.sh and open http://127.0.0.1:5050"""
from __future__ import annotations

import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

import auth
from downloader import (
    BASE_DIR,
    BROWSERS,
    CONTENT_TYPES,
    DEFAULT_TYPES,
    DEFAULT_DOWNLOAD_DIR,
    QUALITIES,
    DownloadRequest,
    build_commands,
    find_tool,
    get_download_dir,
    set_download_dir,
    login_hint,
    subprocess_env,
)

app = Flask(__name__)
app.json.sort_keys = False

MAX_LOG_LINES = 3000
PROGRESS_RE = re.compile(r"^\[download\]\s+\d+(\.\d+)?%")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v"}
AUDIO_EXTS = {".mp3", ".m4a", ".opus", ".aac", ".wav"}


class Job:
    def __init__(self, req: DownloadRequest, commands):
        self.id = uuid.uuid4().hex[:8]
        self.req = req
        self.commands = commands
        self.label = commands[0].label if commands else req.target
        self.status = "queued"
        self.log: list[str] = []
        self.log_offset = 0
        self.created = time.time()
        self.finished: float | None = None
        self.proc: subprocess.Popen | None = None
        self.cancelled = False
        self.lock = threading.Lock()

    def append(self, line: str) -> None:
        with self.lock:
            # Collapse yt-dlp's per-percent progress lines into one updating line.
            if self.log and PROGRESS_RE.match(line) and PROGRESS_RE.match(self.log[-1]):
                self.log[-1] = line
                return
            self.log.append(line)
            if len(self.log) > MAX_LOG_LINES:
                drop = len(self.log) - MAX_LOG_LINES
                del self.log[:drop]
                self.log_offset += drop

    def run(self) -> None:
        self.status = "running"
        failures = 0
        for cmd in self.commands:
            if self.cancelled:
                break
            shown = [Path(a).name if a == sys.executable else a for a in cmd.argv]
            self.append(f"==> {cmd.label}")
            self.append("$ " + shlex.join(shown))
            try:
                self.proc = subprocess.Popen(
                    cmd.argv,
                    cwd=BASE_DIR,
                    env=subprocess_env(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    errors="replace",
                    start_new_session=True,
                )
            except OSError as exc:
                self.append(f"ERROR: could not start downloader: {exc}")
                failures += 1
                continue
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                self.append(line.rstrip("\r\n"))
            if self.proc.wait() != 0:
                failures += 1

        if self.cancelled:
            self.status = "cancelled"
        elif failures:
            self.status = "finished_with_errors"
        else:
            self.status = "done"
        self.finished = time.time()
        if failures:
            with self.lock:
                errors = "\n".join(line for line in self.log if "error" in line.lower())
            if hint := login_hint(self.req, errors):
                self.append(hint)
        self.append(f"--- {self.status.replace('_', ' ')} ---")

    def cancel(self) -> None:
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            # Kill the whole process group: downloaders spawn their own children (yt-dlp, ffmpeg, Chrome).
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def summary(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "created": self.created,
            "finished": self.finished,
        }


JOBS: dict[str, Job] = {}
JOB_QUEUE: "queue.Queue[Job]" = queue.Queue()


def worker() -> None:
    # One job at a time: parallel scraping of the same site quickly triggers rate limits.
    while True:
        job = JOB_QUEUE.get()
        if not job.cancelled:
            job.run()
        else:
            job.status = "cancelled"
        JOB_QUEUE.task_done()


@app.get("/")
def index():
    return render_template(
        "index.html",
        content_types=CONTENT_TYPES,
        default_types=DEFAULT_TYPES,
        qualities=QUALITIES,
        browsers=BROWSERS,
        has_ffmpeg=bool(find_tool("ffmpeg")),
    )


@app.post("/api/jobs")
def create_job():
    data = request.get_json(force=True, silent=True) or {}
    target = (data.get("target") or "").strip()
    if not target:
        return jsonify(error="Enter a username, ID or link."), 400

    try:
        limit = int(data["limit"]) if data.get("limit") not in (None, "") else None
        batch_size = int(data["batch_size"]) if data.get("batch_size") not in (None, "") else 100
    except (TypeError, ValueError):
        return jsonify(error="Max items and batch size must be numbers."), 400

    browser = data.get("browser") or None
    if browser and browser not in BROWSERS:
        return jsonify(error=f"Unknown browser: {browser}"), 400

    req = DownloadRequest(
        target=target,
        platform=data.get("platform") or None,
        types=list(data.get("types") or []),
        limit=limit,
        quality=data.get("quality") or "1080",
        browser=browser,
        cookies_file=(data.get("cookies_file") or "").strip() or None,
        metadata=bool(data.get("metadata")),
        batch_size=batch_size,
    )
    try:
        commands = build_commands(req)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    job = Job(req, commands)
    JOBS[job.id] = job
    JOB_QUEUE.put(job)
    return jsonify(job.summary()), 201


@app.get("/api/jobs")
def list_jobs():
    jobs = sorted(JOBS.values(), key=lambda j: j.created, reverse=True)
    return jsonify([j.summary() for j in jobs])


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    job = JOBS.get(job_id) or abort(404)
    since = request.args.get("since", default=0, type=int)
    with job.lock:
        start = max(since - job.log_offset, 0)
        lines = job.log[start:]
        next_index = job.log_offset + len(job.log)
    return jsonify(job.summary() | {"lines": lines, "from": job.log_offset + start, "next": next_index})


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    job = JOBS.get(job_id) or abort(404)
    job.cancel()
    return jsonify(job.summary())


@app.get("/api/files")
def list_files():
    download_dir = get_download_dir()
    if not download_dir.exists():
        return jsonify([])
    files = []
    for root, dirs, names in os.walk(download_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in names:
            if name.startswith(".") or name.endswith((".part", ".ytdl", ".json", ".txt", ".description")):
                continue
            path = Path(root) / name
            ext = path.suffix.lower()
            kind = "image" if ext in IMAGE_EXTS else "video" if ext in VIDEO_EXTS else "audio" if ext in AUDIO_EXTS else "other"
            stat = path.stat()
            files.append({
                "path": path.relative_to(download_dir).as_posix(),
                "name": name,
                "kind": kind,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return jsonify(files[:300])


@app.get("/files/<path:rel_path>")
def serve_file(rel_path: str):
    return send_from_directory(get_download_dir(), rel_path)


def _volumes() -> list[str]:
    root = Path("/Volumes")
    if not root.is_dir():
        return []
    return sorted(str(p) for p in root.iterdir() if p.is_dir() and not p.is_symlink() and p.name != "Macintosh HD")


def _settings_payload() -> dict:
    download_dir = get_download_dir()
    free = None
    try:
        free = shutil.disk_usage(download_dir if download_dir.exists() else download_dir.parent).free
    except OSError:
        pass
    return {
        "download_dir": str(download_dir),
        "default_download_dir": str(DEFAULT_DOWNLOAD_DIR),
        "available": download_dir.exists(),
        "free_bytes": free,
        "volumes": _volumes(),
    }


@app.get("/api/settings")
def get_settings():
    return jsonify(_settings_payload())


@app.post("/api/settings")
def update_settings():
    data = request.get_json(force=True, silent=True) or {}
    try:
        set_download_dir((data.get("download_dir") or "").strip() or None)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(_settings_payload())


@app.get("/api/auth")
def auth_status():
    return jsonify({site: auth.status(site) for site in auth.SITES})


@app.post("/api/auth/<site>/login")
def auth_login(site: str):
    if site not in auth.SITES:
        abort(404)
    auth.start_login(site)
    return jsonify(auth.status(site))


@app.post("/api/auth/<site>/logout")
def auth_logout(site: str):
    if site not in auth.SITES:
        abort(404)
    auth.logout(site)
    return jsonify(auth.status(site))


@app.post("/api/open-folder")
def open_folder():
    download_dir = get_download_dir()
    if not download_dir.exists():
        return jsonify(error=f"{download_dir} is not available. Is the external drive plugged in?"), 400
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(download_dir)])
    return jsonify(ok=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    threading.Thread(target=worker, daemon=True).start()
    print(f"\n  Open http://127.0.0.1:{port} in your browser\n  Downloads go to {get_download_dir()}\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
