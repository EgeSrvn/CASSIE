@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%stop-cassie.ps1"

if errorlevel 1 (
  echo.
  echo CASSIE failed to stop cleanly.
  pause
  exit /b %errorlevel%
)

echo.
echo CASSIE stop command completed.
pause
