# Start GarageAI backend (8014) and frontend (5173)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$backend = Get-NetTCPConnection -LocalPort 8014 -State Listen -ErrorAction SilentlyContinue
if (-not $backend) {
    Start-Process -FilePath "python" -ArgumentList "-m uvicorn backend.main:app --host 127.0.0.1 --port 8014" -WorkingDirectory $root -WindowStyle Hidden
    Write-Host "Backend started: http://127.0.0.1:8014"
} else {
    Write-Host "Backend already running on port 8014"
}

$frontend = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
if (-not $frontend) {
    Start-Process -FilePath "cmd.exe" -ArgumentList '/c', 'npm run dev -- --host 127.0.0.1' -WorkingDirectory $root -WindowStyle Hidden
    Write-Host "Frontend started: http://127.0.0.1:5173"
} else {
    Write-Host "Frontend already running on port 5173"
}

Start-Sleep -Seconds 3
try {
    Invoke-WebRequest -Uri http://127.0.0.1:8014/health -UseBasicParsing -TimeoutSec 5 | Out-Null
    Write-Host "Backend health: OK"
} catch {
    Write-Host "Backend health: FAILED"
}
