# InstaFBDown

A local tool for downloading posts, reels, stories and videos from **Instagram**, **Facebook** and **YouTube**. Give it a username, profile ID, channel link or post link. It runs entirely on your own computer and has a browser-based interface plus a command-line mode.

> **For personal and educational use only.** Only download content you have the right to keep. Respect the creators' copyright and each platform's terms of service. Don't re-upload other people's content.

## Features

- **One input box for everything:** `natgeo`, `@NASA`, a numeric Facebook ID, or any profile, channel, post, reel or video link. The platform is detected automatically.
- **Instagram:** posts (including multi-photo posts), reels, stories, highlights, tagged posts and profile picture.
- **Facebook:** reels, videos, photos, albums and profile picture. Single video and reel links work too.
- **YouTube:** a channel's videos, Shorts and past live streams, or a single video. Choose 1080p, 720p, 480p, best available, or MP3 audio only.
- **Built-in login for Instagram and Facebook:** click *Log in* and a normal Chrome window opens on the real login page (two-factor codes work). The session is saved locally and used automatically. Your password never passes through the tool.
- **Batch downloading for big Facebook profiles:** reels and videos are collected and downloaded in batches (100 by default), with a pause between batches to avoid rate limits. A failure late in the run never loses earlier batches.
- **Never downloads the same item twice:** downloaded IDs are remembered, so re-running a profile only fetches new items. You can move finished files elsewhere without causing re-downloads.
- **Choose where files go:** save to the project folder or straight to an external drive, with free space shown.
- **Live progress:** a job queue, live logs, a Cancel button, and a gallery of downloaded files.

## Requirements

| Requirement | Why |
|---|---|
| Python 3.10+ | Runs the tool |
| [ffmpeg](https://ffmpeg.org/) | Merges video and audio (YouTube above 360p, Facebook) |
| Google Chrome (or Brave, Edge, Chromium) | Instagram/Facebook login and Facebook reels/videos |
| Node.js or Deno | Needed by yt-dlp for full YouTube support |

**Platform support:** developed and tested on **macOS**. **Windows** and **Linux** are supported in the code but haven't been tested yet. If something doesn't work, please [open an issue](https://github.com/avirusai1/Instafbdown/issues).

Install the requirements:

```bash
# macOS (Homebrew)
brew install python@3.12 ffmpeg node

# Ubuntu / Debian (install Google Chrome separately from google.com/chrome)
sudo apt install python3 python3-venv ffmpeg nodejs
```

```powershell
# Windows (PowerShell); in the Python installer, tick "Add python.exe to PATH"
winget install Python.Python.3.12 Gyan.FFmpeg OpenJS.NodeJS.LTS Google.Chrome
```

## Quick start

**macOS / Linux**

```bash
git clone https://github.com/avirusai1/Instafbdown.git
cd Instafbdown
./run.sh
```

**Windows** (Command Prompt or PowerShell)

```bat
git clone https://github.com/avirusai1/Instafbdown.git
cd Instafbdown
run.bat
```

Then open **http://127.0.0.1:5050** in your browser.

On first run, the launcher (`run.sh` or `run.bat`) creates a virtual environment and installs the Python dependencies. On every run it also updates the downloaders, because these sites change often and fixes ship frequently. No git? Use **Code → Download ZIP** on GitHub, unzip it, and run the launcher from that folder.

For Instagram and Facebook, click **Log in** in the *Accounts* panel first. Both sites show very little to logged-out visitors.

📖 **Full guide: [docs/USAGE.md](docs/USAGE.md)**. It covers logging in, every option, batch downloading, external drives, the command line, and troubleshooting.

## Command line

```bash
./run.sh cli @NASA -p youtube -t videos shorts -n 5          # latest 5 videos + 5 Shorts
./run.sh cli natgeo -p instagram -t posts reels -n 20        # uses your saved Instagram login
./run.sh cli https://www.facebook.com/SOME_PAGE/reels/ --batch-size 50
./run.sh login instagram                                     # log in from the terminal
./run.sh cli --help
```

On Windows, use `run.bat` in place of `./run.sh` (for example `run.bat cli @NASA -p youtube -n 5`).

## How it works

| Part | Handled by |
|---|---|
| YouTube, single Facebook videos/reels | [yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| Instagram, Facebook photos/albums | [gallery-dl](https://github.com/mikf/gallery-dl) |
| Facebook Reels/Videos tabs | `fb_collect.py`: scrolls the tab in a hidden Chrome window using your saved login, collects the links, then hands each batch to yt-dlp |
| Login | `auth.py`: opens a normal Chrome window with its own profile and reads the session cookies once you've logged in |
| Web interface | Flask (`app.py`), plain HTML/CSS/JS (`templates/`, `static/`) |

```
app.py           Web server, job queue, file browser, settings
downloader.py    Turns your input into downloader commands; also the CLI
auth.py          Built-in Instagram/Facebook login
fb_collect.py    Facebook Reels/Videos tab collector with batching
run.sh, run.bat  Setup + launcher (macOS/Linux, Windows)
templates/, static/   Web interface
```

## Privacy and security

- **Runs only on your computer.** The server listens on `127.0.0.1`, so other devices on your network can't reach it.
- **Login sessions are saved in `sessions/`,** readable only by your user account. Treat this folder like a password: anyone who has it can act as your account. Use *Log out* in the interface to delete a session.
- **These are never committed to git:** `sessions/`, `downloads/` and `settings.json` are excluded in `.gitignore`.
- **Bulk downloading can get an account rate-limited or temporarily blocked,** especially on Instagram. Use *Max items* and batching, and consider a secondary account.

## Contributing

Bug reports and pull requests are welcome. If a site changes and downloads break, first restart the tool: the launcher updates yt-dlp and gallery-dl on every start. If that doesn't help, [open an issue](https://github.com/avirusai1/Instafbdown/issues) with the log from the Jobs panel, and remove any usernames or links you don't want to share.

## License

[GNU General Public License v3.0](LICENSE). You're free to use, study, modify and share this software. If you distribute a modified version, it must also be released under the GPL-3.0 with its source code.

## Disclaimer

This project is for learning how media downloaders and browser automation work, and for personal backups of content you're allowed to keep. The authors aren't responsible for how it is used. Downloading content may violate the terms of service of Instagram, Facebook or YouTube, and copyright law in your country. You are responsible for complying with both.
