@echo off
echo ========================================
echo     V47.14 Trading Bot - Prepare for Transfer
echo ========================================
echo.

echo 🧹 Cleaning up temporary files...

REM Remove virtual environment
if exist "backend\venv" (
    echo Removing Python virtual environment...
    rmdir /s /q "backend\venv"
    echo ✅ Virtual environment removed
)

REM Remove node_modules
if exist "frontend\node_modules" (
    echo Removing Node.js modules...
    rmdir /s /q "frontend\node_modules"
    echo ✅ Node modules removed
)

REM Remove Python cache
if exist "backend\__pycache__" (
    echo Removing Python cache...
    rmdir /s /q "backend\__pycache__"
)

for /d /r backend %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"

REM Remove database files (optional - comment out if you want to keep data)
if exist "backend\trading_data_today.db" (
    echo Removing today's database...
    del "backend\trading_data_today.db"
)

if exist "backend\trading_data_all.db" (
    echo Removing historical database...
    del "backend\trading_data_all.db"
)

REM Remove sensitive files (keep templates)
if exist "backend\access_token.json" (
    echo Removing access token file...
    del "backend\access_token.json"
    echo ⚠️ Remember to reconfigure access_token.json on new system
)

REM Remove log files
if exist "backend\trading_log.txt" (
    del "backend\trading_log.txt"
)

REM Remove last run date
if exist "backend\last_run_date.txt" (
    del "backend\last_run_date.txt"
)

echo.
echo ✅ CLEANUP COMPLETE
echo.
echo 📦 Your bot folder is now ready for transfer!
echo.
echo NEXT STEPS:
echo 1. Copy/compress this entire folder
echo 2. Transfer to new system
echo 3. Run SETUP_WINDOWS.bat on new system
echo 4. Configure access_token.json
echo 5. Run START_BOT.bat
echo.
echo The folder size should now be much smaller.
echo.
pause