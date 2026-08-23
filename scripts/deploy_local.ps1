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

function Stop-PortListener {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        Write-Host "Stopping process $($c.OwningProcess) currently listening on port $Port"
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

Stop-PortListener -Port $BackendPort
Stop-PortListener -Port $DashboardPort
Start-Sleep -Seconds 1

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "Starting backend on port $BackendPort..."
Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", "$BackendPort" `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput (Join-Path $LogDir "backend.log") `
    -RedirectStandardError (Join-Path $LogDir "backend.err.log") `
    -WindowStyle Hidden

Write-Host "Starting dashboard on port $DashboardPort..."
Start-Process -FilePath "python" `
    -ArgumentList "-m", "streamlit", "run", "frontend/dashboard.py", "--server.headless", "true", "--server.port", "$DashboardPort" `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput (Join-Path $LogDir "streamlit.log") `
    -RedirectStandardError (Join-Path $LogDir "streamlit.err.log") `
    -WindowStyle Hidden

Write-Host ""
Write-Host "Deployed."
Write-Host "  Backend:   http://127.0.0.1:$BackendPort"
Write-Host "  Dashboard: http://127.0.0.1:$DashboardPort"
Write-Host "  Logs:      $LogDir"
