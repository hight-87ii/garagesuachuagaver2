# Start GarageAI backend (8014) and frontend (5173)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendLog = Join-Path $env:TEMP "garage-ai-backend.log"
$backendErrorLog = Join-Path $env:TEMP "garage-ai-backend-error.log"

$backend = Get-NetTCPConnection -LocalPort 8014 -State Listen -ErrorAction SilentlyContinue
if (-not $backend) {
    Start-Process -FilePath "python" `
        -ArgumentList "-m uvicorn backend.main:app --host 127.0.0.1 --port 8014" `
        -WorkingDirectory $root `
        -RedirectStandardOutput $backendLog `
        -RedirectStandardError $backendErrorLog `
        -WindowStyle Hidden
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

$healthUrl = "http://127.0.0.1:8014/health"
$healthy = $false
for ($attempt = 1; $attempt -le 15; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch {
    }
    Start-Sleep -Seconds 1
}

if ($healthy) {
    Write-Host "Backend health: OK"
} else {
    Write-Host "Backend health: FAILED after 15 seconds"
    if (Test-Path $backendErrorLog) {
        Write-Host "Backend error log: $backendErrorLog"
        Get-Content $backendErrorLog -Tail 20
    }
}
