@echo off
rem Collect notices on this PC and upload to the GitHub web page.
rem Keep this file ASCII-only: Korean text in .bat lines breaks cmd parsing. Messages come from pc_sync.py
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python is not installed. https://www.python.org/downloads/
  pause
  exit /b 1
)
python -m pip install -q --disable-pip-version-check -r requirements.txt
if not defined AX_SOURCES set AX_SOURCES=jexport,jbexport,at,kotra,bizinfo
python pc_sync.py --sources %AX_SOURCES% %*
echo.
pause
