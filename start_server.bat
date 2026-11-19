@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

set "PYTHONW=pythonw.exe"
if exist "C:\Python314\pythonw.exe" set "PYTHONW=C:\Python314\pythonw.exe"

start "" "%PYTHONW%" "%~dp0backend\run_background.py"

if /I "%~1"=="--silent" exit /b 0
if /I "%~1"=="--bg" exit /b 0

powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 20;$i++){ try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:8785/api/health' -TimeoutSec 1; if($r.status -eq 'ok' -and ($r.engine -match 'PM-ECG')){ $ok=$true; break } } catch {} Start-Sleep -Milliseconds 500 }"

start "" "http://127.0.0.1:8785"
exit /b 0
