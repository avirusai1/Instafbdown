"""Built-in login: opens a normal Chrome window, lets the user log in, and saves the
session cookies to sessions/<site>_cookies.txt for gallery-dl / yt-dlp to use.

Instagram and Facebook refuse to load inside iframes, so the login happens in a
separate Chrome window with its own profile. Chrome is started without any
automation flags (sites like Instagram detect those and keep reloading); cookies
are read through Chrome's DevTools endpoint at the browser level, which pages
cannot observe.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from websocket import create_connection

BASE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = BASE_DIR / "sessions"
PROFILES_DIR = SESSIONS_DIR / "profiles"
LOGIN_TIMEOUT = 10 * 60

BROWSER_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)

SITES = {
    "instagram": {
        "name": "Instagram",
        "login_url": "https://www.instagram.com/accounts/login/",
        "domain": "instagram.com",
        "session_cookie": "sessionid",
        "user_cookie": "ds_user_id",
    },
    "facebook": {
        "name": "Facebook",
        "login_url": "https://www.facebook.com/login/",
        "domain": "facebook.com",
        "session_cookie": "xs",
        "user_cookie": "c_user",
    },
}

_flows: dict[str, dict] = {}
_active: dict[str, subprocess.Popen] = {}


def cookies_path(site: str) -> Path:
    return SESSIONS_DIR / f"{site}_cookies.txt"


def saved_cookies(site: str) -> Path | None:
    path = cookies_path(site)
    return path if path.is_file() else None


def _site_cookies(cookies: list[dict], site: str) -> list[dict]:
    domain = SITES[site]["domain"]
    return [c for c in cookies if c["domain"].lstrip(".").endswith(domain)]


def _write_netscape(path: Path, cookies: list[dict]) -> None:
    lines = ["# Netscape HTTP Cookie File", "# Saved by InstaFBDown. Treat this file like a password.", ""]
    for c in cookies:
        domain = c["domain"]
        expires = int(c["expires"]) if c.get("expires", -1) and c["expires"] > 0 else 0
        lines.append("\t".join([
            domain,
            "TRUE" if domain.startswith(".") else "FALSE",
            c.get("path") or "/",
            "TRUE" if c.get("secure") else "FALSE",
            str(expires),
            c["name"],
            c["value"],
        ]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _read_cookie(site: str, name: str) -> str | None:
    path = saved_cookies(site)
    if not path:
        return None
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) == 7 and parts[5] == name:
            return parts[6]
    return None


def find_browser() -> str:
    for path in BROWSER_PATHS:
        if Path(path).exists():
            return path
    for name in ("google-chrome", "chromium", "chromium-browser", "brave-browser"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("Google Chrome (or Brave/Edge/Chromium) is required for login. Install Chrome and retry.")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class DevTools:
    """Minimal client for Chrome's browser-level DevTools websocket."""

    def __init__(self, port: int, proc: subprocess.Popen, timeout: float = 15):
        deadline = time.time() + 20
        while True:
            if proc.poll() is not None:
                raise RuntimeError("Chrome closed right after starting.")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as res:
                    ws_url = json.load(res)["webSocketDebuggerUrl"]
                break
            except OSError:
                if time.time() > deadline:
                    raise RuntimeError("Chrome did not start in time.")
                time.sleep(0.3)
        self.ws = create_connection(ws_url, timeout=timeout, suppress_origin=True)
        self.next_id = 0

    def call(self, method: str, session_id: str | None = None, **params) -> dict:
        self.next_id += 1
        message = {"id": self.next_id, "method": method, "params": params}
        if session_id:
            message["sessionId"] = session_id
        self.ws.send(json.dumps(message))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.next_id:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", "DevTools error"))
                return msg.get("result", {})

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def _set_flow(site: str, state: str, message: str) -> None:
    _flows[site] = {"state": state, "message": message, "updated": time.time()}


def _login_worker(site: str) -> None:
    cfg = SITES[site]
    proc = None
    devtools = None
    try:
        port = free_port()
        profile = PROFILES_DIR / site
        profile.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [
                find_browser(),
                f"--user-data-dir={profile}",
                f"--remote-debugging-port={port}",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=500,850",
                "--new-window",
                cfg["login_url"],
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _active[site] = proc
        devtools = DevTools(port, proc)
        _set_flow(site, "waiting", f"Log in to {cfg['name']} in the window that just opened. "
                                   "It closes by itself when you're done.")

        deadline = time.time() + LOGIN_TIMEOUT
        while time.time() < deadline:
            if proc.poll() is not None:
                _set_flow(site, "cancelled", "Login window was closed before logging in.")
                return
            cookies = _site_cookies(devtools.call("Storage.getCookies")["cookies"], site)
            names = {c["name"] for c in cookies}
            if cfg["session_cookie"] in names and cfg["user_cookie"] in names:
                # Let the site finish setting its post-login cookies.
                time.sleep(3)
                cookies = _site_cookies(devtools.call("Storage.getCookies")["cookies"], site)
                _write_netscape(cookies_path(site), cookies)
                _set_flow(site, "success", f"Logged in to {cfg['name']}. Session saved.")
                try:
                    devtools.call("Browser.close")
                except Exception:  # noqa: BLE001 - browser may close before replying
                    pass
                return
            time.sleep(1.5)
        _set_flow(site, "failed", "Timed out waiting for login.")
    except Exception as exc:  # noqa: BLE001 - surface any launch/browser error to the UI
        _set_flow(site, "failed", str(exc))
    finally:
        if devtools:
            devtools.close()
        if proc:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.terminate()
        _active.pop(site, None)


def start_login(site: str) -> None:
    if _flows.get(site, {}).get("state") in ("starting", "waiting"):
        return
    _set_flow(site, "starting", "Opening a login window…")
    threading.Thread(target=_login_worker, args=(site,), daemon=True).start()


def logout(site: str) -> None:
    proc = _active.get(site)
    if proc and proc.poll() is None:
        proc.terminate()
    path = saved_cookies(site)
    if path:
        path.unlink()
    shutil.rmtree(PROFILES_DIR / site, ignore_errors=True)
    _set_flow(site, "idle", "Logged out.")


def status(site: str) -> dict:
    path = saved_cookies(site)
    flow = _flows.get(site, {"state": "idle", "message": ""})
    return {
        "site": site,
        "name": SITES[site]["name"],
        "logged_in": path is not None,
        "user_id": _read_cookie(site, SITES[site]["user_cookie"]),
        "saved_at": path.stat().st_mtime if path else None,
        "flow": flow["state"],
        "message": flow["message"],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Log in to Instagram/Facebook and save the session for downloads.")
    parser.add_argument("site", choices=list(SITES))
    parser.add_argument("--logout", action="store_true", help="Remove the saved session instead")
    args = parser.parse_args()

    if args.logout:
        logout(args.site)
    else:
        print(f"Opening a browser window. Log in to {SITES[args.site]['name']} there...")
        _login_worker(args.site)
    print(_flows.get(args.site, {}).get("message", "Done."))
