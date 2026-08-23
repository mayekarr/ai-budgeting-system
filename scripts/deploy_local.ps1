# Local "deploy": (re)start the backend + dashboard against the current working tree.
#
# Run manually after merging a PR (`./scripts/deploy_local.ps1`), or automatically by the CD
# workflow (.github/workflows/cd.yml) via a self-hosted GitHub Actions runner. NFR-1: this project
# is local-only for the MVP, so "deploy" means "restart the two local servers with the latest
# code," not a push to a remote host.
param(
    [int]$BackendPort = 8000,
    [int]$DashboardPort = 8501
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Installing dependencies..."
pip install -r (Join-Path $RepoRoot "requirements.txt")

function Test-PortListening {
    param([int]$Port)
    return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).Count -gt 0
}

function Stop-PortListener {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        Write-Host "Stopping process $($c.OwningProcess) currently listening on port $Port"
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

function Wait-PortFree {
    # A fixed sleep after Stop-Process isn't a real guarantee -- the OS can take longer than a
    # second to release a socket under load, and the next Start-Process could then fail to bind.
    # Poll instead, and fail loudly (not silently limp on with a possibly-still-bound port) if it
    # doesn't clear within the timeout.
    param([int]$Port, [int]$TimeoutSeconds = 15)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while (Test-PortListening -Port $Port) {
        if ((Get-Date) -gt $deadline) {
            throw "Port $Port is still in use after ${TimeoutSeconds}s; refusing to start a new server on it."
        }
        Start-Sleep -Milliseconds 250
    }
}

function Wait-PortListening {
    # Confirms the server we just launched actually came up, rather than reporting "Deployed"
    # regardless of whether Start-Process's child process bound the port or crashed on startup.
    param([int]$Port, [string]$Name, [int]$TimeoutSeconds = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while (-not (Test-PortListening -Port $Port)) {
        if ((Get-Date) -gt $deadline) {
            throw "$Name did not start listening on port $Port within ${TimeoutSeconds}s -- check the logs."
        }
        Start-Sleep -Milliseconds 250
    }
}

Stop-PortListener -Port $BackendPort
Stop-PortListener -Port $DashboardPort
Wait-PortFree -Port $BackendPort
Wait-PortFree -Port $DashboardPort

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "Starting backend on port $BackendPort..."
Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", "$BackendPort" `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput (Join-Path $LogDir "backend.log") `
    -RedirectStandardError (Join-Path $LogDir "backend.err.log") `
    -WindowStyle Hidden
Wait-PortListening -Port $BackendPort -Name "Backend"

Write-Host "Starting dashboard on port $DashboardPort..."
Start-Process -FilePath "python" `
    -ArgumentList "-m", "streamlit", "run", "frontend/dashboard.py", "--server.headless", "true", "--server.port", "$DashboardPort" `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput (Join-Path $LogDir "streamlit.log") `
    -RedirectStandardError (Join-Path $LogDir "streamlit.err.log") `
    -WindowStyle Hidden
Wait-PortListening -Port $DashboardPort -Name "Dashboard"

Write-Host ""
Write-Host "Deployed."
Write-Host "  Backend:   http://127.0.0.1:$BackendPort"
Write-Host "  Dashboard: http://127.0.0.1:$DashboardPort"
Write-Host "  Logs:      $LogDir"
