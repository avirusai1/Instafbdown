# How to use InstaFBDown

This guide covers installation, logging in, every download option, big Facebook profiles, external drives, the command line, and troubleshooting. For a short overview, see the [README](../README.md).

- [1. Install](#1-install)
- [2. Start the tool](#2-start-the-tool)
- [3. Log in to Instagram and Facebook](#3-log-in-to-instagram-and-facebook)
- [4. Download something](#4-download-something)
- [5. What you can download](#5-what-you-can-download)
- [6. Big Facebook profiles: batch downloading](#6-big-facebook-profiles-batch-downloading)
- [7. Where files are saved (and external drives)](#7-where-files-are-saved-and-external-drives)
- [8. Stopping, resuming and re-running](#8-stopping-resuming-and-re-running)
- [9. Command line](#9-command-line)
- [10. Troubleshooting](#10-troubleshooting)

---

## 1. Install

You need Python 3.10 or newer, ffmpeg, Node.js (or Deno), and Google Chrome (Brave, Edge or Chromium also work).

> The tool is developed and tested on macOS. Windows and Linux are supported in the code but not yet tested. Please [report problems](https://github.com/avirusai1/Instafbdown/issues).

**macOS** (with [Homebrew](https://brew.sh)):

```bash
brew install python@3.12 ffmpeg node
```

**Ubuntu / Debian:** install Google Chrome from [google.com/chrome](https://www.google.com/chrome/), then:

```bash
sudo apt install python3 python3-venv ffmpeg nodejs
```

**Windows** (PowerShell):

```powershell
winget install Python.Python.3.12 Gyan.FFmpeg OpenJS.NodeJS.LTS Google.Chrome
```

If you install Python from [python.org](https://www.python.org/downloads/) instead, tick **"Add python.exe to PATH"** in the installer. Open a new terminal after installing, so the new commands are found.

Then get the code:

```bash
git clone https://github.com/avirusai1/Instafbdown.git
cd Instafbdown
```

No git? On the GitHub page, click **Code → Download ZIP**, unzip it, and open a terminal in that folder.

There's nothing else to install by hand. On first run, the launcher creates a Python virtual environment (`.venv/`) and installs the Python packages (yt-dlp, gallery-dl, Flask).

## 2. Start the tool

| System | Command |
|---|---|
| macOS / Linux | `./run.sh` |
| Windows | `run.bat` |

Open **http://127.0.0.1:5050** in your browser. Keep the terminal window open while you use the tool; closing it (or pressing `Ctrl+C`) stops the server and any running download.

Each start also updates yt-dlp and gallery-dl. If downloads suddenly stop working, restarting the tool is often the fix.

To use a different port: `PORT=5051 ./run.sh` (macOS/Linux) or `set PORT=5051 && run.bat` (Windows Command Prompt).

> Throughout this guide, `./run.sh` commands work the same on Windows with `run.bat`.

## 3. Log in to Instagram and Facebook

Instagram and Facebook show very little to logged-out visitors. Instagram often says *"user not found"* even for public accounts. YouTube doesn't need a login.

1. In the **Accounts** panel at the top of the page, click **Log in** next to Instagram or Facebook.
2. A separate Chrome window opens on the real login page. Log in normally. Two-factor codes and security checks (such as reCAPTCHA) work as usual.
3. Once you're logged in, the window **closes by itself** and the panel shows **Logged in**.

From then on, every Instagram or Facebook download uses that session automatically.

- **Re-login:** use this if downloads start saying "login required" or "user not found"; the session has probably expired. It's usually instant, because the login window remembers you.
- **Log out:** deletes the saved session from your computer.
- **Separate profile:** the login window uses its own Chrome profile (`sessions/profiles/`), separate from your everyday browser.

> **Why a separate window instead of logging in inside the page?** Instagram and Facebook refuse to load inside other websites, so a real browser window is the only approach that works.

> **Account safety:** bulk downloading can get an account rate-limited or temporarily blocked, especially on Instagram. Start small, use batching, and consider a secondary account.

## 4. Download something

1. **Paste a username, ID, @handle or link** into the first box, for example:
   - `natgeo` (choose *Instagram* as the platform)
   - `@NASA` or `https://www.youtube.com/@NASA`
   - `100044123456789` (a numeric Facebook profile ID; choose *Facebook*)
   - `https://www.facebook.com/SOME_PAGE/reels/`
   - any single post, reel or video link
2. **Platform:** leave it on *Auto-detect* for links. For a bare username or ID, pick the site.
3. **What to download:** click the chips to choose content types (see [section 5](#5-what-you-can-download)).
4. **Max items:** leave blank for everything, or enter a number. Start small (for example 5) the first time.
5. **Video quality** (YouTube and Facebook):
   - *Up to 1080p:* the default. Files play everywhere, including QuickTime.
   - *Up to 720p / 480p:* smaller files.
   - *Best available:* highest resolution, but it may use VP9/AV1 video that needs a player like VLC.
   - *Audio only (MP3)*
6. **Batch size** (Facebook only): see [section 6](#6-big-facebook-profiles-batch-downloading).
7. Click **Start download**.

The job appears under **Jobs** with a live log. Jobs run one at a time, in order; running several against the same site at once quickly triggers rate limits. Finished files appear under **Downloaded files**.

### Advanced options

You normally don't need these.

- **Use login from browser:** use cookies from your everyday browser instead of the built-in login. macOS may show a Keychain prompt; Safari needs Full Disk Access for your terminal app.
- **cookies.txt file path:** use a Netscape-format cookies file exported from a browser extension.
- **Also save captions / descriptions (JSON):** saves post text and metadata next to the media.

## 5. What you can download

| Platform | Content types | Notes |
|---|---|---|
| Instagram | posts, reels, stories, highlights, tagged, avatar | Needs login. A multi-photo post counts as one item for *Max items*. |
| Facebook | reels, videos, photos, albums, avatar | Needs login. Reels and videos are downloaded in batches. |
| YouTube | videos, shorts, streams | No login needed. *Max items* applies to each section separately. |

What different inputs do:

- **A profile or channel** (username, ID or profile link) downloads the content types you selected.
- **A tab link** such as `facebook.com/SOME_PAGE/reels/` or `/videos/` downloads that whole tab.
- **A single post, reel or video link** downloads just that item.

## 6. Big Facebook profiles: batch downloading

Facebook Reels and Videos tabs can hold thousands of items. Neither yt-dlp nor gallery-dl can list these tabs, so the tool does it itself:

1. It opens the tab in a **hidden** Chrome window using your saved Facebook login.
2. It scrolls until it has found *Batch size* new links (100 by default).
3. It downloads that batch.
4. It waits 20 seconds to avoid rate limits.
5. It continues scrolling **from where it stopped** and repeats until the end of the tab, or until *Max items* is reached.

The log shows each batch, for example `=== Batch 3: downloading videos 201–300 ===`.

Why batching helps:

- **Earlier batches are never lost.** If something fails late in a run, every batch before it is already downloaded, and links found for the unfinished batch are downloaded before stopping.
- **The hidden page stays light.** It doesn't have to hold thousands of reels at once.
- **Resuming is free.** Re-running the same link skips everything already downloaded (see [section 8](#8-stopping-resuming-and-re-running)).

A smaller batch size (such as 50) reaches the first downloads sooner; a larger one scrolls longer before each download round.

> **Plan for disk space.** Reels average tens of MB each at 1080p, so a profile with thousands of reels can need well over 100 GB. Choose *Up to 720p* for smaller files, or save to an external drive (see [section 7](#7-where-files-are-saved-and-external-drives)).

## 7. Where files are saved (and external drives)

By default, files are saved inside the project's `downloads/` folder:

```
downloads/
├── youtube/<channel>/<YYYY-MM-DD> - <title> [<id>].mp4
├── instagram/<username>/...
└── facebook/<profile name>/...
```

### Saving to an external drive

In the **Downloaded files** section:

- Click **Use <drive name>** (shown for every connected drive) to save into `<drive>/InstaFBDown`. Or type any full folder path (for example `/Volumes/MyDrive/InstaFBDown` on macOS, `E:\InstaFBDown` on Windows, or `/media/you/MyDrive/InstaFBDown` on Linux) and click **Change folder**.
- **Use default** switches back to the project's `downloads/` folder.
- The free space of the chosen location is shown next to the path.
- A new folder applies to **new** jobs; a job that's already running keeps its original folder.
- If the drive isn't plugged in, new jobs refuse to start and tell you why.

> **Drives formatted for Windows (NTFS) are read-only on macOS.** Use a drive formatted as exFAT or APFS. The tool tells you if it can't write to a folder.

### Moving files yourself

You can move finished videos anywhere, even while a download is running. The record of what's already been downloaded is kept separately (see below), so moved files are **not** downloaded again. Two rules:

1. **Don't move files that are still downloading:** anything ending in `.part`, or with `.f123…` in its name.
2. **Move the media files, not the whole `downloads/` folder.** The download records live inside it as hidden files (see below).

### The download records

Downloaded item IDs are recorded in two hidden files in the project folder:

- `downloads/.yt-dlp-archive.txt` (YouTube and Facebook videos/reels)
- `downloads/.gallery-dl-archive.sqlite3` (Instagram and Facebook photos)

These always stay in the project folder, even when media is saved to an external drive. Keep them: deleting them means the next run downloads everything again.

## 8. Stopping, resuming and re-running

- **Cancel** stops a job immediately, including its hidden browser and any running download.
- **To resume** after a cancel, crash, closed laptop or lost internet, start the same download again. Everything already downloaded is skipped, and it continues from where it stopped. You don't need to remember how far it got.
- **To get new posts later,** re-run the same profile; only new items are downloaded.
- **If a few items fail** (the job ends with *Finished with errors*), re-run it. Those items are retried and everything else is skipped. Items that keep failing have usually been deleted, made private, or are region-restricted.

## 9. Command line

Everything in the web interface is also available from the terminal. `./run.sh cli` (Windows: `run.bat cli`) passes its arguments to `downloader.py`:

```bash
./run.sh cli TARGET [options]
```

On Windows, put links that contain `&` in double quotes, for example `run.bat cli "https://www.youtube.com/watch?v=VIDEO_ID&t=10"`.

| Option | Meaning |
|---|---|
| `TARGET` | Username, ID, @handle, or profile/post/channel link |
| `-p, --platform {instagram,facebook,youtube}` | Required when TARGET is a bare username or ID |
| `-t, --types TYPE [TYPE ...]` | Content types, e.g. `posts reels stories` (see [section 5](#5-what-you-can-download)) |
| `-n, --limit N` | Max items (per section / per tab) |
| `-q, --quality {1080,720,480,best,audio}` | Video quality (default `1080`) |
| `--batch-size N` | Facebook reels/videos batch size (default `100`) |
| `--browser NAME` | Use cookies from your everyday browser instead of the saved login |
| `--cookies FILE` | Use a Netscape cookies.txt file |
| `--metadata` | Also save captions/descriptions as JSON |

Examples:

```bash
./run.sh cli @NASA -p youtube -t videos shorts -n 5
./run.sh cli https://www.youtube.com/watch?v=VIDEO_ID -q audio
./run.sh cli natgeo -p instagram -t posts reels -n 20
./run.sh cli SOME_PAGE -p facebook -t reels videos --batch-size 50
```

Log in or out from the terminal:

```bash
./run.sh login instagram
./run.sh login facebook --logout
```

## 10. Troubleshooting

**Instagram says "user not found" or "login required".**
You're not logged in, or the session expired. Click **Log in** (or **Re-login**) in the Accounts panel.

**The login window shows a reCAPTCHA or security check.**
That's normal for a login from a new browser. Complete it and the window closes by itself once you're in.

**The login window closed but the panel says "Not logged in".**
The window was closed before login finished. Click **Log in** again.

**YouTube videos are only 360p, or merging fails.**
ffmpeg is missing. Install it (`brew install ffmpeg`, `sudo apt install ffmpeg`, or `winget install Gyan.FFmpeg`) and restart the tool. The page shows a warning when ffmpeg isn't found.

**"Python 3.10+ is required" (or `python` isn't found on Windows).**
Install Python 3.10 or newer (see [section 1](#1-install)). On Windows, make sure "Add python.exe to PATH" was ticked, then open a new terminal.

**"Google Chrome (or Brave/Edge/Chromium) is required for login".**
Install Google Chrome. On Linux, the browser must be on your PATH as `google-chrome`, `chromium`, `brave-browser` or `microsoft-edge`.

**YouTube asks you to "sign in to confirm you're not a bot".**
Open **Advanced options**, set **Use login from browser** to a browser where you're logged in to YouTube, and try again.

**"Can't write to /Volumes/…"**
The drive is probably formatted as NTFS, which macOS can only read. Use an exFAT or APFS drive.

**"Download folder … is not available".**
The external drive isn't connected. Plug it in, or click **Use default**.

**A Facebook job ended with "Finished with errors".**
Check the end of the log: it shows how many items were downloaded and how many batches had errors. Re-run the same link to retry the failed items; everything else is skipped.

**Downloads that used to work suddenly fail.**
The sites change often. Restart the tool with `./run.sh`; it updates the downloaders on every start.

**Port 5050 is already in use.**
Start with `PORT=5051 ./run.sh` and open http://127.0.0.1:5051.
