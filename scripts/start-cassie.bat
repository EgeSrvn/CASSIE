@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start-cassie.ps1"

if errorlevel 1 (
  echo.
  echo CASSIE failed to start.
  pause
  exit /b %errorlevel%
)

echo.
echo CASSIE startup command completed.
pause
