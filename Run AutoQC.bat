@echo off
setlocal EnableExtensions
title AutoQC Launcher

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "PYTHON_EXE=%ROOT%\.venv\Scripts\python.exe"
set "FRONTEND_DIR=%ROOT%\frontend"
set "BACKEND_PORT=8000"
set "FRONTEND_BASE_PORT=5173"
set "FRONTEND_MAX_PORT=5199"
set "FRONTEND_PORT="
set "BACKEND_URL=http://127.0.0.1:%BACKEND_PORT%"
set "BACKEND_ALREADY_RUNNING=0"

echo.
echo ========================================
echo   AutoQC - Natural Gas Drawing QC
echo ========================================
echo Project root: %ROOT%
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python was not found on PATH.
  echo Install Python 3.11+ or add Python to PATH, then rerun this file.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm was not found on PATH.
  echo Install Node.js LTS, then rerun this file.
  pause
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  echo Creating Python virtual environment...
  python -m venv "%ROOT%\.venv"
  if errorlevel 1 (
    echo ERROR: Failed to create Python virtual environment.
    pause
    exit /b 1
  )
)

echo Installing/updating backend dependencies...
"%PYTHON_EXE%" -m pip install -r "%ROOT%\requirements.txt"
if errorlevel 1 (
  echo ERROR: Failed to install backend dependencies.
  pause
  exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules" (
  echo Installing frontend dependencies...
  set "NPM_CONFIG_CACHE=%LOCALAPPDATA%\npm-cache"
  npm --prefix "%FRONTEND_DIR%" install
  if errorlevel 1 (
    echo ERROR: Failed to install frontend dependencies.
    pause
    exit /b 1
  )
)

echo Checking required ports...
for /f %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$start=%FRONTEND_BASE_PORT%; $end=%FRONTEND_MAX_PORT%; for ($port=$start; $port -le $end; $port++) { $busy = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue; if (-not $busy) { Write-Output $port; exit 0 } }; exit 1"') do set "FRONTEND_PORT=%%P"
if not defined FRONTEND_PORT (
  echo ERROR: No available frontend port found between %FRONTEND_BASE_PORT% and %FRONTEND_MAX_PORT%.
  echo Close an existing AutoQC Frontend window or free a port, then rerun this file.
  pause
  exit /b 1
)
set "FRONTEND_URL=http://127.0.0.1:%FRONTEND_PORT%"
if not "%FRONTEND_PORT%"=="%FRONTEND_BASE_PORT%" (
  echo Frontend port %FRONTEND_BASE_PORT% is already in use. Using %FRONTEND_PORT% instead.
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$backend = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort %BACKEND_PORT% -State Listen -ErrorAction SilentlyContinue; if ($backend) { exit 1 } else { exit 0 }"
if errorlevel 1 (
  set "BACKEND_ALREADY_RUNNING=1"
  echo Backend port %BACKEND_PORT% is already in use. Reusing the existing backend at %BACKEND_URL%.
)

if "%BACKEND_ALREADY_RUNNING%"=="0" (
  echo Starting backend at %BACKEND_URL% ...
  start "AutoQC Backend" cmd /k "cd /d ""%ROOT%"" && ""%PYTHON_EXE%"" -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port %BACKEND_PORT%"
)

echo Starting frontend at %FRONTEND_URL% ...
start "AutoQC Frontend" cmd /k "cd /d ""%FRONTEND_DIR%"" && set ""NPM_CONFIG_CACHE=%LOCALAPPDATA%\npm-cache"" && npm run dev -- --host 127.0.0.1 --port %FRONTEND_PORT% --strictPort"

echo Waiting for app to start...
timeout /t 5 /nobreak >nul
start "" "%FRONTEND_URL%"

echo.
echo AutoQC is starting. Browser opened to %FRONTEND_URL%.
echo Keep the Backend and Frontend terminal windows open while using the app.
echo Close those two windows to stop AutoQC.
echo.
pause
