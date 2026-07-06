# NBACore Studio v8 — Development Start Script (PowerShell)
# Usage: .\start.ps1 [dev|prod]

param([string]$Mode = "dev")

if ($Mode -eq "prod") {
    Write-Host "Starting NBACore Studio v8 (production)..."
    $port = if ($env:SERVER_PORT) { $env:SERVER_PORT } else { "5577" }
    $workers = if ($env:WORKERS) { $env:WORKERS } else { "4" }
    gunicorn backend.app:create_app --factory --bind "0.0.0.0:$port" --workers $workers --worker-class uvicorn.workers.UvicornWorker --timeout 120 --access-logfile - --error-logfile -
} else {
    Write-Host "Starting NBACore Studio v8 (development)..."
    $host_addr = if ($env:SERVER_HOST) { $env:SERVER_HOST } else { "127.0.0.1" }
    $port = if ($env:SERVER_PORT) { $env:SERVER_PORT } else { "5577" }
    uvicorn backend.app:create_app --factory --reload --host $host_addr --port $port
}
