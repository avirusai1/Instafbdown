"""Core download logic shared by the web UI (app.py) and the command line.

YouTube and single Facebook videos are handled by yt-dlp; Instagram and
Facebook photos are handled by gallery-dl; Facebook Reels/Videos tabs are
listed by fb_collect.py and then downloaded with yt-dlp.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from auth import SITES as AUTH_SITES
from auth import saved_cookies

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DOWNLOAD_DIR = BASE_DIR / "downloads"
# "Already downloaded" records stay here even when videos go to another folder or drive,
# so moving files or switching folders never triggers re-downloads.
ARCHIVE_DIR = DEFAULT_DOWNLOAD_DIR
SETTINGS_FILE = BASE_DIR / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def get_download_dir() -> Path:
    custom = load_settings().get("download_dir")
    return Path(custom) if custom else DEFAULT_DOWNLOAD_DIR


def set_download_dir(path: str | None) -> Path:
    """Validate and save a new download folder (None/empty resets to the default)."""
    settings = load_settings()
    if not path:
        settings.pop("download_dir", None)
        target = DEFAULT_DOWNLOAD_DIR
    else:
        target = Path(path).expanduser()
        if not target.is_absolute():
            raise ValueError("Use a full path, e.g. /Volumes/MyDrive/InstaFBDown")
        if target.parts[:2] == ("/", "Volumes") and len(target.parts) > 2:
            drive = Path(*target.parts[:3])
            if not drive.is_dir():
                raise ValueError(f"Drive '{drive.name}' is not connected. Plug it in and try again.")
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".write-test"
            probe.write_text("ok")
            probe.unlink()
        except OSError as exc:
            hint = (" If this is an external drive formatted for Windows (NTFS), macOS can only read it; "
                    "use an exFAT or APFS drive.") if str(target).startswith("/Volumes/") else ""
            raise ValueError(f"Can't write to {target}: {exc.strerror or exc}.{hint}") from exc
        settings["download_dir"] = str(target)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2) + "\n")
    return target


def ensure_download_dir() -> Path:
    target = get_download_dir()
    if target != DEFAULT_DOWNLOAD_DIR and not target.parent.exists():
        raise ValueError(f"Download folder {target} is not available. Is the external drive plugged in?")
    target.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    return target

PLATFORMS = ("instagram", "facebook", "youtube")

CONTENT_TYPES = {
    "instagram": ["posts", "reels", "stories", "highlights", "tagged", "avatar"],
    "facebook": ["reels", "videos", "photos", "albums", "avatar"],
    "youtube": ["videos", "shorts", "streams"],
}

DEFAULT_TYPES = {
    "instagram": ["posts", "reels"],
    "facebook": ["reels", "videos", "photos"],
    "youtube": ["videos", "shorts"],
}

QUALITIES = {
    "1080": "Up to 1080p (plays everywhere)",
    "720": "Up to 720p",
    "480": "Up to 480p",
    "best": "Best available (may need VLC)",
    "audio": "Audio only (MP3)",
}

BROWSERS = ("chrome", "safari", "firefox", "edge", "brave", "chromium", "opera", "vivaldi")

YOUTUBE_CHANNEL_RE = re.compile(
    r"^https?://(?:www\.|m\.)?youtube\.com/(?:@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+)/?(?:[?#].*)?$",
    re.IGNORECASE,
)
FACEBOOK_VIDEO_RE = re.compile(r"fb\.watch/|/videos/[^/?#]+|/watch/?\?|/reel/\d|/share/[vr]/", re.IGNORECASE)
FACEBOOK_TAB_RE = re.compile(r"/(?:reels|videos)/?(?:[?#].*)?$|[?&]sk=(?:reels_tab|videos)\b", re.IGNORECASE)
FACEBOOK_NON_PROFILE = {"watch", "reel", "share", "photo", "photo.php", "groups", "events", "pages",
                        "story.php", "permalink.php", "media", "marketplace", "login"}
FACEBOOK_PHOTO_TYPES = ("photos", "albums", "avatar")


@dataclass
class DownloadRequest:
    target: str
    platform: str | None = None
    types: list[str] = field(default_factory=list)
    limit: int | None = None
    quality: str = "1080"
    browser: str | None = None
    cookies_file: str | None = None
    metadata: bool = False
    batch_size: int = 100


@dataclass
class Command:
    label: str
    argv: list[str]


def detect_platform(target: str) -> str | None:
    t = target.lower()
    if "instagram.com" in t or "instagr.am" in t:
        return "instagram"
    if "facebook.com" in t or "fb.watch" in t or "fb.com" in t:
        return "facebook"
    if "youtube.com" in t or "youtu.be" in t:
        return "youtube"
    return None


def normalize_target(platform: str, target: str) -> str:
    """Turn a username / ID / partial link into a full URL."""
    target = target.strip()
    if re.match(r"^https?://", target, re.IGNORECASE):
        return target
    if "/" in target and "." in target.split("/")[0]:
        return "https://" + target

    handle = target.lstrip("@").strip("/")
    if not handle or not re.fullmatch(r"[\w.\-]+", handle):
        raise ValueError(f"'{target}' doesn't look like a valid username, ID or link.")

    if platform == "instagram":
        return f"https://www.instagram.com/{handle}/"
    if platform == "facebook":
        if handle.isdigit():
            return f"https://www.facebook.com/profile.php?id={handle}"
        return f"https://www.facebook.com/{handle}"
    if re.fullmatch(r"UC[\w-]{22}", handle):
        return f"https://www.youtube.com/channel/{handle}"
    return f"https://www.youtube.com/@{handle}"


def resolve(req: DownloadRequest) -> tuple[str, str]:
    platform = detect_platform(req.target) or req.platform
    if platform not in PLATFORMS:
        raise ValueError("Couldn't tell which site this is. Pick Instagram, Facebook or YouTube.")
    return platform, normalize_target(platform, req.target)


LOGIN_ERROR_RE = re.compile(r"log ?in|not found|checkpoint|cookies|401|403|private|session", re.IGNORECASE)


def login_hint(req: DownloadRequest, output: str | None = None) -> str | None:
    """Advice to show when a download fails, if missing login is the likely cause.

    When the downloader output is given, the hint is only returned if it looks login-related.
    """
    if req.browser or req.cookies_file:
        return None
    if output is not None and not LOGIN_ERROR_RE.search(output):
        return None
    try:
        platform, _ = resolve(req)
    except ValueError:
        return None
    if platform not in AUTH_SITES:
        return None
    name = AUTH_SITES[platform]["name"]
    if saved_cookies(platform):
        return (f"Hint: if {name} says login is required or 'user not found', your saved session may have "
                f"expired. Click 'Log in' next to {name} at the top of the page to refresh it.")
    return (f"Hint: {name} hides most content from logged-out visitors (it often reports 'user not found'). "
            f"Click 'Log in' next to {name} at the top of the page (or run: ./run.sh login {platform}).")


def find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
        candidate = Path(prefix) / name
        if candidate.exists():
            return str(candidate)
    return None


def subprocess_env() -> dict[str, str]:
    """Environment for child processes, with ffmpeg / JS runtimes on PATH."""
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    extra = [str(Path(p).parent) for p in (find_tool("ffmpeg"), find_tool("deno"), find_tool("node")) if p]
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def _cookie_args(req: DownloadRequest, platform: str) -> list[str]:
    if req.browser:
        return ["--cookies-from-browser", req.browser]
    if req.cookies_file:
        path = Path(req.cookies_file).expanduser()
        if not path.is_file():
            raise ValueError(f"Cookies file not found: {path}")
        return ["--cookies", str(path)]
    saved = saved_cookies(platform) if platform in AUTH_SITES else None
    if saved:
        return ["--cookies", str(saved)]
    return []


def _ytdlp_command(req: DownloadRequest, platform: str, urls: list[str], template: str) -> list[str]:
    argv = [
        sys.executable, "-m", "yt_dlp",
        "--newline",
        "--ignore-errors",
        "--no-overwrites",
        "--embed-metadata",
        "--download-archive", str(ARCHIVE_DIR / ".yt-dlp-archive.txt"),
        "-o", str(get_download_dir() / template),
    ]

    if req.quality == "audio":
        argv += ["-f", "ba/b", "-x", "--audio-format", "mp3"]
    elif req.quality == "best":
        argv += ["-f", "bv*+ba/b", "--merge-output-format", "mp4"]
    else:
        height = req.quality if req.quality in QUALITIES else "1080"
        argv += ["-f", "bv*+ba/b", "-S", f"res:{height},vcodec:h264,acodec:m4a", "--merge-output-format", "mp4"]

    if req.limit:
        argv += ["--playlist-items", f"1:{req.limit}"]
    if req.metadata:
        argv += ["--write-info-json", "--write-description", "--write-thumbnail", "--convert-thumbnails", "jpg"]

    ffmpeg = find_tool("ffmpeg")
    if ffmpeg:
        argv += ["--ffmpeg-location", ffmpeg]
    if not find_tool("deno"):
        node = find_tool("node")
        if node:
            argv += ["--js-runtimes", f"node:{node}"]

    argv += _cookie_args(req, platform)
    return argv + urls


def _gallerydl_command(req: DownloadRequest, platform: str, url: str, types: list[str]) -> list[str]:
    argv = [
        sys.executable, "-m", "gallery_dl",
        "-d", str(get_download_dir()),
        "--download-archive", str(ARCHIVE_DIR / ".gallery-dl-archive.sqlite3"),
        "-o", f"include={','.join(types)}",
    ]
    if platform == "facebook":
        argv += ["-o", "videos=ytdl"]
    if req.limit:
        argv += ["--post-range", f"1-{req.limit}"]
    if req.metadata:
        argv += ["--write-metadata"]
    argv += _cookie_args(req, platform)
    return argv + [url]


def build_commands(req: DownloadRequest) -> list[Command]:
    platform, url = resolve(req)
    ensure_download_dir()
    valid = CONTENT_TYPES[platform]
    unknown = [t for t in req.types if t not in valid]
    if unknown:
        raise ValueError(f"Unsupported content type(s) for {platform}: {', '.join(unknown)}")
    if req.limit is not None and req.limit < 1:
        raise ValueError("Limit must be a positive number.")
    if req.batch_size < 1:
        raise ValueError("Batch size must be a positive number.")

    if platform == "youtube":
        urls = [url]
        if YOUTUBE_CHANNEL_RE.match(url):
            base = re.sub(r"[?#].*$", "", url).rstrip("/")
            urls = [f"{base}/{t}" for t in (req.types or DEFAULT_TYPES["youtube"])]
        template = "youtube/%(channel,uploader|Unknown channel)s/%(upload_date>%Y-%m-%d|undated)s - %(title).150B [%(id)s].%(ext)s"
        return [Command(f"YouTube: {url}", _ytdlp_command(req, platform, urls, template))]

    types = req.types or DEFAULT_TYPES[platform]
    if platform == "facebook":
        return _facebook_commands(req, url, types)
    return [Command(f"Instagram: {url}", _gallerydl_command(req, platform, url, types))]


def _is_facebook_profile(url: str) -> bool:
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    if segments == ["profile.php"]:
        return "id" in parse_qs(parsed.query)
    return len(segments) == 1 and segments[0].lower() not in FACEBOOK_NON_PROFILE


def _facebook_tab_url(profile_url: str, tab: str) -> str:
    if "profile.php" in profile_url:
        return f"{profile_url}&sk={'reels_tab' if tab == 'reels' else 'videos'}"
    return re.sub(r"[?#].*$", "", profile_url).rstrip("/") + f"/{tab}/"


def _fb_collect_command(req: DownloadRequest, tab_urls: list[str]) -> list[str]:
    template = "facebook/%(uploader|Unknown)s/%(title).100B [%(id)s].%(ext)s"
    ytdlp = _ytdlp_command(replace(req, limit=None), "facebook", [], template)
    argv = [sys.executable, str(BASE_DIR / "fb_collect.py"), *tab_urls, "--batch-size", str(req.batch_size)]
    if req.limit:
        argv += ["--limit", str(req.limit)]
    argv += _cookie_args(req, "facebook")
    return argv + ["--"] + ytdlp


def _facebook_commands(req: DownloadRequest, url: str, types: list[str]) -> list[Command]:
    if FACEBOOK_VIDEO_RE.search(url):
        template = "facebook/%(uploader|Unknown)s/%(title).100B [%(id)s].%(ext)s"
        return [Command(f"Facebook video: {url}", _ytdlp_command(req, "facebook", [url], template))]
    if FACEBOOK_TAB_RE.search(url):
        return [Command(f"Facebook reels/videos: {url}", _fb_collect_command(req, [url]))]
    photo_types = [t for t in types if t in FACEBOOK_PHOTO_TYPES]
    if not _is_facebook_profile(url):
        return [Command(f"Facebook: {url}", _gallerydl_command(req, "facebook", url, photo_types or ["photos"]))]

    commands = []
    if photo_types:
        commands.append(Command(f"Facebook {', '.join(photo_types)}: {url}",
                                _gallerydl_command(req, "facebook", url, photo_types)))
    tab_urls = [_facebook_tab_url(url, t) for t in ("reels", "videos") if t in types]
    if tab_urls:
        commands.append(Command(f"Facebook reels/videos: {url}", _fb_collect_command(req, tab_urls)))
    return commands


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download posts, reels and videos from Instagram, Facebook and YouTube.",
        epilog="Examples:\n"
               "  python downloader.py natgeo -p instagram -t posts reels -n 20 --browser chrome\n"
               "  python downloader.py https://www.youtube.com/@NASA -t videos shorts -n 5\n"
               "  python downloader.py zuck -p facebook -t photos --browser chrome",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("target", help="Username, ID, @handle, or full profile/post/channel link")
    parser.add_argument("-p", "--platform", choices=PLATFORMS, help="Needed when target is a bare username/ID")
    parser.add_argument("-t", "--types", nargs="+", default=[], help="Content types, e.g. posts reels stories")
    parser.add_argument("-n", "--limit", type=int, help="Max items to download (per section)")
    parser.add_argument("-q", "--quality", choices=list(QUALITIES), default="1080")
    parser.add_argument("--browser", choices=BROWSERS, help="Use your logged-in browser session (cookies)")
    parser.add_argument("--cookies", dest="cookies_file", help="Path to a Netscape cookies.txt file")
    parser.add_argument("--metadata", action="store_true", help="Also save captions/descriptions as JSON")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Facebook reels/videos: download in batches of this many (default 100)")
    args = parser.parse_args()

    req = DownloadRequest(**vars(args))
    try:
        commands = build_commands(req)
    except ValueError as exc:
        parser.error(str(exc))

    exit_code = 0
    for cmd in commands:
        print(f"==> {cmd.label}", flush=True)
        exit_code |= subprocess.call(cmd.argv, cwd=BASE_DIR, env=subprocess_env())
    if exit_code and (hint := login_hint(req)):
        print(f"\n{hint}")
    print(f"\nFiles saved under {get_download_dir()}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
