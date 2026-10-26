@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if "%~1"=="" (
  python "%~dp0sync_plugins.py" --menu
) else (
  python "%~dp0sync_plugins.py" %*
)
if errorlevel 1 pause
endlocal
