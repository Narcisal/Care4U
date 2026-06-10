# Kill existing XTTS process on port 8082, then relaunch.
# Called automatically by tts_service.py when XTTS trips the circuit breaker.
# Set XTTS_RESTART_SCRIPT=<absolute path to this file> in .env to enable.

$xttsDir  = "C:\Users\user\often_use\NCKU\grade3-2\專題\0511\xtts"
$python   = "$xttsDir\venv\Scripts\python.exe"
$port     = 8082

Write-Host "XTTS 重啟中..."

# Kill process holding port 8082
$pids = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
foreach ($p in $pids) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    Write-Host "已終止 PID $p"
}

Start-Sleep -Seconds 3

# Start XTTS in a new hidden window
Start-Process -FilePath $python `
    -ArgumentList "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "$port" `
    -WorkingDirectory $xttsDir `
    -WindowStyle Hidden

Write-Host "XTTS 已重新啟動（port $port），模型載入約需 20-30 秒"
