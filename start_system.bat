@echo off
title Junior Aladdin — System Startup
cd /d "F:\junior aladdin v2"

echo ========================================
echo  Junior Aladdin — Starting System
echo ========================================
echo.

:: ── Check .env ──
if not exist ".env" (
    echo [WARNING] .env file not found.
    echo   Copy .env.example to .env and fill in your Angel One credentials.
    echo   The system will start, but live broker features won't work.
    echo.
)

:: ── Step 1: Kill any existing process on port 8080 ──
echo [1/4] Cleaning up port 8080...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8080 ^| findstr LISTENING') do (
    taskkill //F //PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

:: ── Step 2: Start the API server ──
echo [2/4] Starting API server...
start /B python -m junior_aladdin.side_b_api.api_server > server.log 2>&1

:: ── Step 3: Wait for server to be ready (max 30s) ──
echo [3/4] Waiting for server to be ready...
set retries=0
:waitloop
set /a retries+=1
if %retries% gtr 15 (
    echo.
    echo [ERROR] Server failed to start after 30 seconds.
    echo   Check server.log for details.
    pause
    exit /b 1
)
timeout /t 2 /nobreak >nul
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/')" >nul 2>&1
if errorlevel 1 goto waitloop

:: ── Step 4: Open Dashboard ──
echo [4/4] Opening Dashboard...
start http://localhost:8080/dashboard/

echo.
echo ========================================
echo  System is RUNNING!
echo  Dashboard: http://localhost:8080/dashboard/
echo  API Root:  http://localhost:8080/
echo ========================================
echo.
echo  Daily routine:
echo    1. Set mode:     ALERT / PAPER / REAL
echo    2. Set capital:  Enter your daily limit
echo    3. Monitor:      Health, Captain, Execution panels
echo.
echo  Press Ctrl+C in this window to stop the server.
echo ========================================

:: Keep window open so user can Ctrl+C to stop
pause >nul
