@echo off
echo ========================================
echo      V47.14 Trading Bot - Stopping
echo ========================================
echo.

echo 🛑 Stopping all bot processes...

REM Kill Python processes (backend)
taskkill /f /im python.exe 2>nul
if %errorlevel% == 0 (
    echo ✅ Backend stopped
) else (
    echo ℹ️ No backend processes found
)

REM Kill Node processes (frontend)
taskkill /f /im node.exe 2>nul
if %errorlevel% == 0 (
    echo ✅ Frontend stopped
) else (
    echo ℹ️ No frontend processes found
)

echo.
echo ✅ V47.14 Trading Bot stopped successfully
echo.
pause