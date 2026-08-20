@echo off
setlocal

set "TDM_ENGLISH_ONLY=1"
set "WEB_HOST=127.0.0.1"
if not defined WEB_PORT set "WEB_PORT=8080"

if exist "%~dp0env\Scripts\python.exe" (
    "%~dp0env\Scripts\python.exe" "%~dp0main.py" --headless -vv
) else (
    python "%~dp0main.py" --headless -vv
)
