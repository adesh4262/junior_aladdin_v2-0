@echo off
title Junior Aladdin V2 — System Runner
cd /d "F:\junior aladdin v2"

echo ========================================
echo  Junior Aladdin V2.0 — Starting System
echo ========================================
echo.

:: ── Check .env ──
if not exist ".env" (
    echo [INFO] .env file not found.
    echo   The system will start in ALERT mode with Paper broker.
    echo   For live trading, copy .env.example to .env and fill credentials.
    echo.
)

:: ── Step 1: Kill any existing Python processes ──
echo [1/5] Cleaning up previous sessions...
taskkill //F //IM python.exe >nul 2>&1
timeout /t 3 /nobreak >nul
echo       Done.

:: ── Step 2: Start SystemRunner (API + WebSocket + Pipeline) ──
echo [2/5] Starting System Runner (Mode: PAPER, Capital: Rs 50,000)...
start /B python -m junior_aladdin.system_runner --mode PAPER --capital 50000 > system_runner.log 2>&1

:: ── Step 3: Wait for API server to be ready (max 45s) ──
echo [3/5] Waiting for API server... (this may take 20-30 seconds)
set retries=0
:waitloop
set /a retries+=1
if %retries% gtr 22 (
    echo.
    echo [ERROR] Server failed to start after ~45 seconds.
    echo   Check system_runner.log for details.
    type system_runner.log | findstr "error" 2>nul
    type system_runner.log | findstr "Error" 2>nul
    echo.
    pause
    exit /b 1
)
timeout /t 2 /nobreak >nul
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)" >nul 2>&1
if errorlevel 1 goto waitloop

echo       Server READY on http://127.0.0.1:8080

:: ── Step 4: Check Angel One login status ──
echo [4/5] Checking connection status...
python -c "
import urllib.request, json
try:
    resp = urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=5)
    data = json.loads(resp.read())
    h = data.get('connection_status', 'UNKNOWN')
    o = data.get('overall_status', 'UNKNOWN')
    print(f'  Health: {o} | Connection: {h}')
    resp2 = urllib.request.urlopen('http://127.0.0.1:8080/api/market/snapshot', timeout=5)
    data2 = json.loads(resp2.read())
    ltp = data2.get('ltp', 0)
    sess = data2.get('session', '')
    print(f'  LTP: {ltp} | Session: {sess}')
except Exception as e:
    print(f'  Status check error: {e}')
" 2>&1
echo.

:: ── Step 5: Open Dashboard ──
echo [5/5] Opening Dashboard...
start http://localhost:8080/dashboard/

echo ========================================
echo  SYSTEM IS RUNNING!
echo ========================================
echo.
echo  Dashboard: http://localhost:8080/dashboard/
echo  API Root:  http://localhost:8080/
echo  Log:       system_runner.log
echo.
echo  What you can do:
echo    1. Open Dashboard — see live LTP, heads, captain
echo    2. Set Mode (ALERT/PAPER/REAL) via API commands
echo    3. Monitor Captain decisions on each 1m candle close
echo.
echo  Press Ctrl+C in this window to stop the system.
echo ========================================

:: Keep window open so user can Ctrl+C to stop
echo.
echo  Press any key to minimize to tray...
pause >nul
exit
