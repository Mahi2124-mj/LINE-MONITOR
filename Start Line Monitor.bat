@echo off
REM ============================================================
REM  Line Monitor - double-click to start. Opens http://localhost:6010
REM  (Port 6002 belongs to another project and is not used here.)
REM ============================================================
title Line Monitor - starting
cd /d "%~dp0"
set "URL=http://localhost:6010"
set "HEALTH=http://127.0.0.1:6010/api/health"

REM Already running? Just open the dashboard.
powershell -NoProfile -Command "try { Invoke-RestMethod '%HEALTH%' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if %errorlevel%==0 goto open

REM First run: install everything once.
if not exist "backend\.venv\Scripts\python.exe" (
    echo First start: installing components, this happens only once...
    call "%~dp0setup.bat"
    if errorlevel 1 goto fail
)
if not exist "frontend\dist\index.html" (
    echo Building the dashboard...
    pushd frontend
    call npm install
    call npm run build
    popd
)

echo Starting Line Monitor server on %URL% ...
REM Runs in the background without a window and restarts itself if it ever crashes.
REM Stop it with "Stop Line Monitor.bat". Logs: backend\data\server.log, supervisor.log
start "" /d "%~dp0backend" "%~dp0backend\.venv\Scripts\pythonw.exe" supervisor.py

REM Wait until the server answers (max 90 s).
powershell -NoProfile -Command "$d=(Get-Date).AddSeconds(90); while((Get-Date) -lt $d){ try { Invoke-RestMethod '%HEALTH%' -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Milliseconds 700 } }; exit 1"
if errorlevel 1 goto fail

:open
if not "%LM_NO_BROWSER%"=="1" start "" "%URL%"
exit /b 0

:fail
echo.
echo Line Monitor could not start. See backend\data\server.log and backend\data\console.log for the error.
pause
exit /b 1
