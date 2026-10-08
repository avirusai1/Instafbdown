"""Collect reel/video links from Facebook profile tabs (Reels, Videos) and download them in batches.

Neither gallery-dl nor yt-dlp can list these tabs, so this opens the tab in a hidden
Chrome window using the saved login cookies and scrolls through it. Every time
`--batch-size` new links are found, that batch is downloaded with the yt-dlp command
given after "--"; then scrolling resumes where it left off. A failure late in a huge
profile therefore never loses the batches already downloaded.

Usage: python fb_collect.py TAB_URL [TAB_URL ...] [--limit N] [--batch-size N] [--batch-pause SECONDS]
                            [--cookies FILE | --cookies-from-browser B] -- YT_DLP_ARGV...
"""
from __future__ import annotations

import argparse
import http.cookiejar
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

from websocket import WebSocketTimeoutException

from auth import DevTools, find_browser, free_port

LINK_RE = re.compile(r"facebook\.com/(?:reel/(\d+)|(?:[^/?#]+/videos/(?:[^/?#]+/)?|watch/?\?v=)(\d+))")
SCROLL_PAUSE = 2.5
MAX_IDLE_ROUNDS = 6
MAX_ROUNDS = 5000
EVAL_RETRIES = 3

# Only returns links not reported before, so each round stays cheap on pages with thousands of reels.
COLLECT_JS = """(() => {
  const seen = window.__ifdSeen || (window.__ifdSeen = new Set());
  const fresh = [];
  for (const a of document.querySelectorAll('a[href*="/reel/"], a[href*="/videos/"], a[href*="/watch"]')) {
    if (!seen.has(a.href)) { seen.add(a.href); fresh.push(a.href); }
  }
  window.scrollTo(0, document.documentElement.scrollHeight);
  return { url: location.href, links: fresh };
})()"""


def load_cookies(cookies_file: str | None, browser: str | None) -> list[dict]:
    if browser:
        from yt_dlp.cookies import extract_cookies_from_browser
        jar = extract_cookies_from_browser(browser)
    elif cookies_file:
        jar = http.cookiejar.MozillaCookieJar(cookies_file)
        jar.load(ignore_discard=True, ignore_expires=True)
    else:
        return []

    cookies = []
    for c in jar:
        if not c.domain.lstrip(".").endswith("facebook.com"):
            continue
        cookie = {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path or "/", "secure": bool(c.secure)}
        if c.expires:
            cookie["expires"] = c.expires
        cookies.append(cookie)
    return cookies


def normalize(href: str) -> str | None:
    match = LINK_RE.search(href)
    if not match:
        return None
    if match.group(1):
        return f"https://www.facebook.com/reel/{match.group(1)}"
    return f"https://www.facebook.com/watch/?v={match.group(2)}"


def _evaluate(devtools: DevTools, session: str) -> dict:
    for attempt in range(EVAL_RETRIES):
        try:
            result = devtools.call("Runtime.evaluate", session, expression=COLLECT_JS, returnByValue=True)
            return result.get("result", {}).get("value") or {"url": "", "links": []}
        except WebSocketTimeoutException:
            if attempt == EVAL_RETRIES - 1:
                raise
            print("  page is slow to respond, retrying…", flush=True)
    raise AssertionError("unreachable")


def collect_batches(devtools: DevTools, session: str, url: str, limit: int | None,
                    batch_size: int, seen: set[str]) -> Iterator[list[str]]:
    """Scrolls `url` and yields lists of up to `batch_size` new links.

    The browser page stays where it is while the caller downloads a batch, so
    scrolling picks up exactly where it stopped.
    """
    devtools.call("Page.navigate", session, url=url)
    time.sleep(6)
    pending: list[str] = []
    total = 0
    idle = 0
    try:
        for _ in range(MAX_ROUNDS):
            value = _evaluate(devtools, session)
            if "/login" in value["url"] or "/checkpoint" in value["url"]:
                raise RuntimeError("Facebook asked to log in, so the saved session has expired. "
                                   "Click 'Re-login' next to Facebook and try again.")
            new = 0
            for href in value["links"]:
                link = normalize(href)
                if link and link not in seen and not (limit and total >= limit):
                    seen.add(link)
                    pending.append(link)
                    total += 1
                    new += 1
            if new:
                print(f"  found {total} so far…", flush=True)
            while len(pending) >= batch_size:
                yield pending[:batch_size]
                pending = pending[batch_size:]
            if limit and total >= limit:
                break
            idle = 0 if new else idle + 1
            if idle >= MAX_IDLE_ROUNDS:
                break
            time.sleep(SCROLL_PAUSE)
    except Exception:
        if pending:
            print(f"Collection stopped early; downloading the {len(pending)} link(s) already found first.", flush=True)
            yield pending
        raise
    if pending:
        yield pending
    reason = "reached the max items limit" if limit and total >= limit else "reached the end of the tab"
    print(f"Finished collecting from {url}: {reason} ({total} video(s) found).", flush=True)


def download_batch(ytdlp_argv: list[str], links: list[str]) -> int:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", prefix="instafbdown-links-", delete=False) as batch:
        batch.write("\n".join(links) + "\n")
    try:
        return subprocess.call(ytdlp_argv + ["--batch-file", batch.name])
    finally:
        Path(batch.name).unlink(missing_ok=True)


def main() -> int:
    # Turn "Cancel" (SIGTERM) into a normal exit so the hidden browser and temp files are cleaned up.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    argv = sys.argv[1:]
    if "--" not in argv:
        print("Missing '-- <yt-dlp command>'", file=sys.stderr)
        return 2
    split = argv.index("--")
    own_args, ytdlp_argv = argv[:split], argv[split + 1:]

    parser = argparse.ArgumentParser()
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--limit", type=int, help="Max videos per tab")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--batch-pause", type=float, default=20, help="Seconds to wait between batches")
    parser.add_argument("--cookies")
    parser.add_argument("--cookies-from-browser")
    args = parser.parse_args(own_args)
    batch_size = max(1, args.batch_size)

    cookies = load_cookies(args.cookies, args.cookies_from_browser)
    if not cookies:
        print("Facebook reels/videos need a login. Click 'Log in' next to Facebook at the top of the page.")
        return 1

    profile_dir = tempfile.mkdtemp(prefix="instafbdown-chrome-")
    port = free_port()
    proc = subprocess.Popen(
        [
            find_browser(),
            "--headless=new",
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--mute-audio",
            "--window-size=1280,2400",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    devtools = None
    failed = False
    download_errors = 0
    batch_no = 0
    done = 0
    try:
        devtools = DevTools(port, proc, timeout=60)
        user_agent = devtools.call("Browser.getVersion")["userAgent"].replace("HeadlessChrome", "Chrome")
        devtools.call("Storage.setCookies", cookies=cookies)
        target = devtools.call("Target.createTarget", url="about:blank")["targetId"]
        session = devtools.call("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
        devtools.call("Emulation.setUserAgentOverride", session, userAgent=user_agent)

        seen: set[str] = set()
        for url in args.urls:
            print(f"Collecting links from {url} (batches of {batch_size})", flush=True)
            for batch in collect_batches(devtools, session, url, args.limit, batch_size, seen):
                if batch_no and args.batch_pause > 0:
                    print(f"Pausing {args.batch_pause:g}s before the next batch to avoid rate limits…", flush=True)
                    time.sleep(args.batch_pause)
                batch_no += 1
                print(f"=== Batch {batch_no}: downloading videos {done + 1}–{done + len(batch)} ===", flush=True)
                if download_batch(ytdlp_argv, batch) != 0:
                    download_errors += 1
                done += len(batch)
                print(f"=== Batch {batch_no} finished ({done} video(s) processed so far) ===", flush=True)
    except Exception as exc:  # noqa: BLE001 - batches already downloaded are kept
        failed = True
        print(f"ERROR while collecting links: {exc or type(exc).__name__}", flush=True)
    finally:
        if devtools:
            try:
                devtools.call("Browser.close")
            except Exception:  # noqa: BLE001
                pass
            devtools.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)

    if not done and not failed:
        print("No reels/videos found. The profile may have none, or they may be hidden from your account.")
        return 1
    print(f"Done: {done} video(s) in {batch_no} batch(es)"
          + (f", {download_errors} batch(es) had download errors" if download_errors else "") + ".", flush=True)
    return 1 if failed or download_errors else 0


if __name__ == "__main__":
    sys.exit(main())
