@echo off
REM One-shot: seize the Tello link, LAND it, then reconnect internet.
REM Make sure the Tello is powered on (and airborne if you want to see it land).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0land_tello_oneshot.ps1"
echo.
pause
