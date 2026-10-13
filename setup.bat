@echo off
REM One-time setup: Python venv + backend packages, frontend packages + production build.
setlocal
cd /d "%~dp0"

echo === Backend (Python 3.10 - 3.12 recommended) ===
if not exist backend\.venv (
    py -3.12 -m venv backend\.venv 2>nul || python -m venv backend\.venv
)
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto :err

echo === Frontend ===
cd frontend
call npm install
if errorlevel 1 goto :err
call npm run build
if errorlevel 1 goto :err
cd ..

echo.
echo Setup complete. Double-click "Start Line Monitor.bat"
goto :eof

:err
echo Setup failed - see the messages above.
exit /b 1
