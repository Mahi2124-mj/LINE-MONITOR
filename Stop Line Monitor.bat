@echo off
REM Stops the Line Monitor server and its auto-restart guard. Only the Python process listening on
REM port 6010 is stopped - never Tailscale (which also serves port 6010 to the tailnet) or other projects.
cd /d "%~dp0"
type nul > "backend\data\stop.flag"
powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort 6010 -State Listen -ErrorAction SilentlyContinue | Where-Object { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName -in 'python','pythonw' }; if ($c) { $c.OwningProcess | Sort-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force }; 'Line Monitor stopped.' } else { 'Line Monitor is not running.' }; Start-Sleep -Seconds 2"
