@echo off
echo ========================================
echo    V47.14 Trading Bot - Windows Setup
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://python.org
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit /b 1
)

REM Check if Node.js is installed
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is not installed or not in PATH
    echo Please install Node.js from https://nodejs.org
    pause
    exit /b 1
)

echo ✅ Python and Node.js found
echo.

REM Create Python virtual environment
echo 📦 Creating Python virtual environment...
cd backend
if not exist "venv" (
    python -m venv venv
    echo ✅ Virtual environment created
) else (
    echo ✅ Virtual environment already exists
)

REM Activate virtual environment and install Python dependencies
echo 📦 Installing Python dependencies...
call venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo ❌ Failed to install Python dependencies
    pause
    exit /b 1
)
echo ✅ Python dependencies installed

REM Deactivate virtual environment
call venv\Scripts\deactivate.bat
cd ..

REM Install Node.js dependencies
echo 📦 Installing Node.js dependencies...
cd frontend
call npm install
if errorlevel 1 (
    echo ❌ Failed to install Node.js dependencies
    pause
    exit /b 1
)
echo ✅ Node.js dependencies installed
cd ..

REM Create configuration files if they don't exist
echo 🔧 Setting up configuration files...
if not exist "backend\access_token.json" (
    echo {> backend\access_token.json
    echo   "access_token": "YOUR_ACCESS_TOKEN_HERE",>> backend\access_token.json
    echo   "user_id": "YOUR_USER_ID_HERE">> backend\access_token.json
    echo }>> backend\access_token.json
    echo ✅ Created access_token.json template
)

if not exist "backend\strategy_params.json" (
    copy "backend\strategy_params.json.template" "backend\strategy_params.json" >nul 2>&1
    echo ✅ Created strategy_params.json from template
)

echo.
echo ========================================
echo           SETUP COMPLETE! ✅
echo ========================================
echo.
echo NEXT STEPS:
echo 1. Edit backend\access_token.json with your Kite credentials
echo 2. Review backend\strategy_params.json for trading parameters  
echo 3. Run START_BOT.bat to launch the trading bot
echo 4. Access the web interface at http://localhost:3000
echo.
echo Press any key to continue...
pause >nul