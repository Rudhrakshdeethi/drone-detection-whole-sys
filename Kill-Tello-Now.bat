@echo off
REM One-shot EMERGENCY: seize the Tello link, CUT THE MOTORS instantly, then
REM reconnect internet. This does NOT land gently — the drone drops the moment
REM the motors stop, so use it only at low altitude / over something soft.
REM For a normal controlled descent, run Land-Tello-Now.bat instead.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0land_tello_oneshot.ps1" -Emergency
echo.
pause
