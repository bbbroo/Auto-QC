$ErrorActionPreference = "Stop"

Write-Host "Starting Natural Gas Engineering Copilot backend on http://127.0.0.1:8000"
Start-Process powershell -WindowStyle Hidden -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$PSScriptRoot\..'; python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000"
)

Write-Host "Starting frontend on http://127.0.0.1:5173"
Start-Process powershell -WindowStyle Hidden -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$PSScriptRoot\..\frontend'; npm run dev -- --host 127.0.0.1"
)

Write-Host "Open http://127.0.0.1:5173"

