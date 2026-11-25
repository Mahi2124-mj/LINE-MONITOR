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
echo This takes about 15-30 seconds (longer right after the PC was switched on).
echo Please wait - the dashboard opens by itself. No need to start it again.
REM Runs in the background without a window and restarts itself if it ever crashes. A second start is harmless
REM (only one supervisor runs). Stop it with "Stop Line Monitor.bat". Logs: backend\data\server.log, supervisor.log
start "" /d "%~dp0backend" "%~dp0backend\.venv\Scripts\pythonw.exe" supervisor.py

REM Wait until the server answers (max 3 min), showing the seconds so far.
powershell -NoProfile -Command "$t0=Get-Date; while(((Get-Date)-$t0).TotalSeconds -lt 180){ try { Invoke-RestMethod '%HEALTH%' -TimeoutSec 2 | Out-Null; Write-Host ''; exit 0 } catch { Write-Host -NoNewline ([char]13 + '  waiting for the server: ' + [int]((Get-Date)-$t0).TotalSeconds + ' s '); Start-Sleep -Milliseconds 700 } }; exit 1"
if errorlevel 1 goto fail

:open
if not "%LM_NO_BROWSER%"=="1" start "" "%URL%"
exit /b 0

:fail
echo.
echo Line Monitor could not start. See backend\data\server.log and backend\data\console.log for the error.
pause
exit /b 1
