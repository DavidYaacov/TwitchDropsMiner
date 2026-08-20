@echo off
setlocal

set "WEB_HOST=127.0.0.1"
if not defined WEB_PORT set "WEB_PORT=8080"

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0main.py" -vv
) else (
    python "%~dp0main.py" -vv
)
