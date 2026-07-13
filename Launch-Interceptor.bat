@echo off
REM Double-click to start the interceptor against the PlutoX drone.
REM It joins the drone WiFi, arms LAND, and reconnects your internet when you exit.
cd /d "%~dp0"
REM (Uses the WiFi profile already saved on this PC; the password is not stored in the repo.)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0interceptor.ps1" -DroneSsid PlutoX_2025_1043
echo.
pause
