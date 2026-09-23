@echo off
REM Start the Feral Media Library (Windows) — double-click friendly like
REM ComfyUI portable: creates the Python environment on first start, keeps
REM it current when the pinned dependencies change, and opens the browser.
REM
REM   start.bat                        → config.toml, server on port 8765
REM                                      (or [web] port from the config)
REM   start.bat --config archive.toml  → second instance: own config with
REM                                      its own DB + its own port
REM                                      (see docs/instanzen.md)
REM   start.bat --port 9000            → all arguments go to
REM                                      "python -m feral.web"
REM
REM The server opens the browser itself (--browser) once the port is
REM actually accepted — it knows the effective port from the full
REM precedence chain (--port > $PORT > config > 8765), this file does not
REM need to compute it. The DB path comes from the config ([database]
REM path, default .\feral.sqlite) — hence NO forced --db here.
setlocal
cd /d "%~dp0"

REM -- Find Python (3.12+, py launcher preferred) --------------------------------
set "PY="
py -3.13 -c "exit()" >nul 2>&1 && set "PY=py -3.13"
if not defined PY py -3.12 -c "exit()" >nul 2>&1 && set "PY=py -3.12"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1 && set "PY=python"
if not defined PY (
  echo ERROR: Python 3.12+ not found. Please install it from https://www.python.org
  echo        and tick "Add python.exe to PATH" in the setup.
  pause
  exit /b 1
)

REM -- Create / update the environment ---------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo First start: creating the Python environment ^(.venv^) ...
  %PY% -m venv .venv || (pause & exit /b 1)
)

REM Only reinstall when the pinned dependencies have changed.
fc /b requirements.txt ".venv\.deps-stamp" >nul 2>&1
if errorlevel 1 (
  echo Installing/updating dependencies ...
  REM Hash-checking mode: pip installs ONLY the packages and files listed in
  REM requirements.txt (pip itself included) and builds nothing from source.
  ".venv\Scripts\python.exe" -m pip install --quiet --require-hashes --only-binary=:all: -r requirements.txt || (pause & exit /b 1)
  REM Older versions installed fml itself with "pip install -e ."; the .pth
  REM file below replaces that, so the old entry is removed.
  ".venv\Scripts\python.exe" -m pip show --quiet feral-media-library >nul 2>&1 && ".venv\Scripts\python.exe" -m pip uninstall --quiet --yes feral-media-library
  copy /y requirements.txt ".venv\.deps-stamp" >nul
)

REM Make the fml sources (src\) importable in this environment via a .pth file.
REM Needs no build step and no extra package; rewritten on every start so a
REM moved folder keeps working.
".venv\Scripts\python.exe" -c "import pathlib, sysconfig; pathlib.Path(sysconfig.get_paths()['purelib'], 'fml-src.pth').write_text(str(pathlib.Path('src').resolve()) + '\n')" || (pause & exit /b 1)

REM -- Check ffmpeg/ffprobe (for video metadata and thumbnails) --------------------
where ffprobe >nul 2>&1
if errorlevel 1 if not exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ffprobe.exe" (
  echo.
  echo NOTE: ffmpeg/ffprobe not found. Videos will still be taken in,
  echo       but without metadata and without video thumbnails.
  choice /c YN /m "Install it now via winget (Gyan.FFmpeg)"
  if not errorlevel 2 (
    winget install --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    echo Done - the app will find ffmpeg automatically from now on.
  )
)

REM -- Start the server (opens the browser itself, see header comment) -------------
".venv\Scripts\python.exe" -m feral.web --browser %*
pause
