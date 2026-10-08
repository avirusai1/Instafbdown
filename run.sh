#!/usr/bin/env bash
# Sets up a virtualenv on first run, keeps the downloaders up to date, and starts the web UI.
# Usage: ./run.sh            -> web UI at http://127.0.0.1:5050
#        ./run.sh cli ARGS   -> command-line mode (see: ./run.sh cli --help)
#        ./run.sh login instagram|facebook [--logout]
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 \
                 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1 \
     && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10+ is required." >&2
  echo "  macOS:         brew install python@3.12" >&2
  echo "  Ubuntu/Debian: sudo apt install python3 python3-venv" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating virtual environment with $PY ..."
  "$PY" -m venv .venv
fi

# Sites change often; yt-dlp and gallery-dl ship fixes almost weekly.
echo "Checking for downloader updates ..."
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q --upgrade -r requirements.txt

if ! command -v ffmpeg >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/ffmpeg ]; then
  echo "Warning: ffmpeg not found. Install it with 'brew install ffmpeg' (macOS) or 'sudo apt install ffmpeg' (Linux)." >&2
fi

if [ "${1:-}" = "cli" ]; then
  shift
  exec .venv/bin/python downloader.py "$@"
fi
if [ "${1:-}" = "login" ]; then
  shift
  exec .venv/bin/python auth.py "$@"
fi
exec .venv/bin/python app.py
