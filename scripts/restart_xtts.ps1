# Kill existing XTTS process on port 8082.
# The auto-restart wrapper (run_loop.ps1) will relaunch it automatically.
# Set XTTS_RESTART_SCRIPT=<absolute path to this file> in .env to enable.

$port = 8082

Write-Host "正在終止 XTTS (port $port)..."

$pids = @()
try {
    $pids = (Get-NetTCPConnection -LocalPort $port -ErrorAction Stop).OwningProcess | Sort-Object -Unique
} catch {
    $lines = netstat -ano | Select-String ":$port\s"
    foreach ($line in $lines) {
        if ($line -match '\s(\d+)\s*$') {
            $pids += [int]$Matches[1]
        }
    }
    $pids = $pids | Sort-Object -Unique
}

foreach ($p in $pids) {
    if ($p -gt 0) {
        try {
            Stop-Process -Id $p -Force -ErrorAction Stop
            Write-Host "已終止 PID $p"
        } catch {
            taskkill /F /PID $p 2>$null
        }
    }
}

Write-Host "XTTS 已終止，run_loop.ps1 會自動重啟"
