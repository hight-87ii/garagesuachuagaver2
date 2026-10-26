# Stop GarageAI servers on ports 8014 and 5173.
# Uvicorn --reload tạo một tiến trình con; dừng cả hai để không giữ lại API cũ.
$backend = Get-NetTCPConnection -LocalPort 8014 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($backendPid in $backend) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$backendPid" |
        Where-Object { $_.Name -like 'python*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $backendPid -Force -ErrorAction SilentlyContinue
}
Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Write-Host "GarageAI servers stopped."
