@echo off
REM Builds "dist\Cadence.exe": one file (under 10 MB, so it fits on Discord) with the
REM web UI, font, icons and phrase dictionary inside.
REM Size savings: unused standard-library parts are left out, and OpenSSL is replaced by
REM Windows' own HTTPS for update checks (see packaging\rthook_nossl.py and updater.py).
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "Cadence" ^
  --icon "assets\cadence.ico" ^
  --add-data "web;web" ^
  --add-data "assets\cadence.ico;assets" ^
  --add-data "humanizer\phrases.json;humanizer" ^
  --collect-all webview ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput.mouse._win32 ^
  --runtime-hook "packaging\rthook_nossl.py" ^
  --exclude-module ssl --exclude-module _ssl --exclude-module _hashlib ^
  --exclude-module setuptools --exclude-module pkg_resources --exclude-module packaging ^
  --exclude-module pydoc --exclude-module pydoc_data --exclude-module _pyrepl ^
  --exclude-module unittest --exclude-module doctest --exclude-module pdb ^
  --exclude-module PyInstaller --exclude-module pefile ^
  --exclude-module lzma --exclude-module _lzma --exclude-module bz2 --exclude-module _bz2 ^
  --exclude-module compression.zstd --exclude-module _zstd ^
  --exclude-module tkinter --exclude-module sqlite3 --exclude-module xmlrpc ^
  --exclude-module ensurepip --exclude-module venv --exclude-module curses --exclude-module lib2to3 ^
  main.py
if errorlevel 1 exit /b 1
for %%F in ("dist\Cadence.exe") do echo Built: %%~fF  (%%~zF bytes)
