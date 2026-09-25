param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "status", "restart")]
    [string]$Command = "status"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $Root ".runtime"
$Logs = Join-Path $Runtime "logs"
$BackendPid = Join-Path $Runtime "backend.pid"
$FrontendPid = Join-Path $Runtime "frontend.pid"

function Read-AppPid([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $value = (Get-Content -LiteralPath $Path -Raw).Trim()
    if ($value -notmatch '^\d+$') { return $null }
    return [int]$value
}

function Test-AppProcess([string]$Path) {
    $processId = Read-AppPid $Path
    if ($null -eq $processId) { return $false }
    return $null -ne (Get-Process -Id $processId -ErrorAction SilentlyContinue)
}

function Stop-AppProcess([string]$Path, [string]$Name) {
    $processId = Read-AppPid $Path
    if ($null -ne $processId) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            Stop-Process -Id $processId -Force
            Write-Host "Stopped $Name (PID $processId)."
        }
    }
    Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
}

function Install-Requirements {
    $VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        $SystemPython = (Get-Command python -ErrorAction SilentlyContinue).Source
        if (-not $SystemPython) { throw "Python 3 was not found on PATH." }
        Write-Host "Creating Python virtual environment..."
        & $SystemPython -m venv (Join-Path $Root ".venv")
    }

    Write-Host "Checking Python requirements..."
    & $VenvPython -m pip install --disable-pip-version-check --quiet -r (Join-Path $Root "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }

    $Npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if (-not $Npm) { throw "Node.js and npm were not found on PATH." }
    Write-Host "Checking frontend requirements..."
    $Vite = Join-Path $Root "frontend\node_modules\vite\bin\vite.js"
    $React = Join-Path $Root "frontend\node_modules\react\package.json"
    if (-not (Test-Path -LiteralPath $Vite) -or -not (Test-Path -LiteralPath $React)) {
        Push-Location (Join-Path $Root "frontend")
        try {
            & $Npm install --silent
            if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        } finally { Pop-Location }
    }
}

function Start-App {
    if ((Test-AppProcess $BackendPid) -or (Test-AppProcess $FrontendPid)) {
        Write-Host "The application is already running. Use 'app status' for details."
        return
    }
    Install-Requirements
    New-Item -ItemType Directory -Force -Path $Runtime, $Logs | Out-Null

    $VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
    $backend = Start-Process -FilePath $VenvPython `
        -ArgumentList @("-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Logs "backend.out.log") `
        -RedirectStandardError (Join-Path $Logs "backend.err.log")
    Set-Content -LiteralPath $BackendPid -Value $backend.Id

    $Node = (Get-Command node -ErrorAction Stop).Source
    $Vite = Join-Path $Root "frontend\node_modules\vite\bin\vite.js"
    $frontend = Start-Process -FilePath $Node `
        -ArgumentList @("`"$Vite`"", "--host", "127.0.0.1", "--port", "5173") `
        -WorkingDirectory (Join-Path $Root "frontend") -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Logs "frontend.out.log") `
        -RedirectStandardError (Join-Path $Logs "frontend.err.log")
    Set-Content -LiteralPath $FrontendPid -Value $frontend.Id

    Start-Sleep -Seconds 2
    if (-not (Test-AppProcess $BackendPid)) {
        Stop-AppProcess $FrontendPid "frontend"
        throw "Backend failed to start. See .runtime/logs/backend.err.log."
    }
    if (-not (Test-AppProcess $FrontendPid)) {
        Stop-AppProcess $BackendPid "backend"
        throw "Frontend failed to start. See .runtime/logs/frontend.err.log."
    }
    Write-Host "Representment Desk started."
    Write-Host "Frontend: http://127.0.0.1:5173"
    Write-Host "API:      http://127.0.0.1:8000/docs"
}

function Stop-App {
    Stop-AppProcess $FrontendPid "frontend"
    Stop-AppProcess $BackendPid "backend"
}

function Show-Status {
    $backendState = if (Test-AppProcess $BackendPid) { "running" } else { "stopped" }
    $frontendState = if (Test-AppProcess $FrontendPid) { "running" } else { "stopped" }
    Write-Host "Backend:  $backendState"
    Write-Host "Frontend: $frontendState"
}

switch ($Command) {
    "start" { Start-App }
    "stop" { Stop-App }
    "status" { Show-Status }
    "restart" { Stop-App; Start-App }
}
