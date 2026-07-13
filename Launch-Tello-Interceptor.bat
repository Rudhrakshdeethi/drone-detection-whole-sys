@echo off
REM Double-click to start the interceptor against the Tello demo drone.
REM Joins TELLO-954B1F (open WiFi), arms LAND, reconnects internet when you exit.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0interceptor.ps1" -DroneSsid TELLO-954B1F
echo.
pause
