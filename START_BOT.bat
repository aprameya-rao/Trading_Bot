@echo off
title V47.14 Trading Bot
echo ========================================
echo      V47.14 Trading Bot - Starting
echo ========================================
echo.

REM Check if setup was completed
if not exist "backend\venv" (
    echo ❌ Setup not completed! Please run SETUP_WINDOWS.bat first
    pause
    exit /b 1
)

REM Check if configuration files exist
if not exist "backend\access_token.json" (
    echo ❌ access_token.json not found! Please configure your Kite credentials
    pause
    exit /b 1
)

echo 🚀 Starting V47.14 Trading Bot...
echo.
echo Frontend will be available at: http://localhost:3000
echo Backend API will be available at: http://localhost:8000
echo.
echo To stop the bot, close this window or press Ctrl+C
echo.

REM Start backend in background
echo 🔧 Starting backend server...
cd backend
start /b cmd /c "venv\Scripts\activate.bat && python main.py"
cd ..

REM Wait a moment for backend to start
timeout /t 3 /nobreak >nul

REM Start frontend
echo 🎨 Starting frontend...
cd frontend
npm run dev

REM If we get here, frontend stopped
echo.
echo 🛑 Frontend stopped. Cleaning up...
taskkill /f /im python.exe 2>nul
echo ✅ Bot stopped
pause