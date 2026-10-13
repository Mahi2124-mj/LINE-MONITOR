@echo off
REM DEVELOPERS ONLY (UI hot reload). Normal use: double-click "Line Monitor" on the Desktop -> http://localhost:6010
cd /d "%~dp0.."
start "Line Monitor - backend" /d "%~dp0..\backend" "%~dp0..\backend\.venv\Scripts\python.exe" run.py
start "Line Monitor - frontend dev" /d "%~dp0..\frontend" cmd /k npm run dev
powershell -NoProfile -Command "Start-Sleep -Seconds 6"
start "" http://localhost:6012
