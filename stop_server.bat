@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

powershell -NoProfile -Command ^
  "try { Stop-ScheduledTask -TaskName 'PM-ECG-Hybrid-Server' -ErrorAction SilentlyContinue } catch {}; " ^
  "Get-CimInstance Win32_Process | Where-Object { (($_.Name -match '^pythonw?\.exe$') -and ($_.CommandLine -match 'run_background\.py|backend\.server:app.*8785')) -or (($_.Name -ieq 'cloudflared.exe') -and ($_.CommandLine -match '8785')) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo [OK] Da dung may chu PM-ECG Hybrid AI va Cloudflare Tunnel (http://127.0.0.1:8785).
exit /b 0
