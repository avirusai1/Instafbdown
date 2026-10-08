@echo off
rem Windows launcher. Sets up a virtualenv on first run, keeps the downloaders up to date, and starts the web UI.
rem Usage: run.bat            -> web UI at http://127.0.0.1:5050
rem        run.bat cli ARGS   -> command-line mode (see: run.bat cli --help)
rem        run.bat login instagram^|facebook [--logout]
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>&1 && py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python 3.10+ is required. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^).
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment ...
  %PY% -m venv .venv || exit /b 1
)

rem Sites change often; yt-dlp and gallery-dl ship fixes almost weekly.
echo Checking for downloader updates ...
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q --upgrade -r requirements.txt || exit /b 1

where ffmpeg >nul 2>&1 || echo Warning: ffmpeg not found. Install it with: winget install Gyan.FFmpeg

set "SCRIPT=app.py"
if /i "%~1"=="cli" set "SCRIPT=downloader.py"
if /i "%~1"=="login" set "SCRIPT=auth.py"
if "%SCRIPT%"=="app.py" goto :run

rem Collect every argument after "cli"/"login" (batch's %* can't skip the first one).
shift
set "ARGS="
:collect
if "%~1"=="" goto :run
set ARGS=%ARGS% %1
shift
goto :collect

:run
".venv\Scripts\python.exe" %SCRIPT% %ARGS%
exit /b %errorlevel%
