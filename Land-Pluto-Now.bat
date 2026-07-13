@echo off
REM One-shot: join the PlutoX (alongside the phone), send a controlled LAND,
REM then reconnect internet. Make sure the Pluto is ON and the laptop is NEAR it.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0land_pluto_oneshot.ps1"
echo.
pause
