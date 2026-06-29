$ErrorActionPreference = "Stop"

$BackendPort = 8000
$FrontendBasePort = 5173
$FrontendMaxPort = 5199
$Root = Resolve-Path "$PSScriptRoot\.."
$FrontendDir = Join-Path $Root "frontend"

function Test-LocalPortInUse([int]$Port) {
    $listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$listener
}

$FrontendPort = $null
foreach ($Port in $FrontendBasePort..$FrontendMaxPort) {
    if (-not (Test-LocalPortInUse $Port)) {
        $FrontendPort = $Port
        break
    }
}

if (-not $FrontendPort) {
    throw "No available frontend port found between $FrontendBasePort and $FrontendMaxPort."
}

if (Test-LocalPortInUse $BackendPort) {
    Write-Host "Backend port $BackendPort is already in use. Reusing http://127.0.0.1:$BackendPort."
} else {
    Write-Host "Starting AutoQC backend on http://127.0.0.1:$BackendPort"
    Start-Process powershell -WindowStyle Hidden -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$Root'; python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port $BackendPort"
    )
}

if ($FrontendPort -ne $FrontendBasePort) {
    Write-Host "Frontend port $FrontendBasePort is already in use. Using $FrontendPort instead."
}

Write-Host "Starting frontend on http://127.0.0.1:$FrontendPort"
Start-Process powershell -WindowStyle Hidden -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$FrontendDir'; npm run dev -- --host 127.0.0.1 --port $FrontendPort --strictPort"
)

Write-Host "Open http://127.0.0.1:$FrontendPort"
