@echo off
REM Double-click this to start the counter-drone interceptor.
REM It joins the drone WiFi, arms LAND, and reconnects your internet when you exit.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0interceptor.ps1"
echo.
pause
