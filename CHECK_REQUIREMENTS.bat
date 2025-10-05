@echo off
echo ========================================
echo    V47.14 Trading Bot - System Check
echo ========================================
echo.

echo 🔍 Checking system requirements...
echo.

REM Check Python
echo [1/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python not found - Please install Python 3.8+ from https://python.org
    set "missing=true"
) else (
    for /f "tokens=2" %%i in ('python --version 2^>^&1') do echo ✅ Python found: %%i
)

REM Check Node.js
echo [2/4] Checking Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Node.js not found - Please install Node.js from https://nodejs.org
    set "missing=true"
) else (
    for /f %%i in ('node --version 2^>nul') do echo ✅ Node.js found: %%i
)

REM Check npm
echo [3/4] Checking npm...
npm --version >nul 2>&1
if errorlevel 1 (
    echo ❌ npm not found - Usually comes with Node.js
    set "missing=true"
) else (
    for /f %%i in ('npm --version 2^>nul') do echo ✅ npm found: %%i
)

REM Check pip
echo [4/4] Checking pip...
pip --version >nul 2>&1
if errorlevel 1 (
    echo ❌ pip not found - Usually comes with Python
    set "missing=true"
) else (
    for /f "tokens=2" %%i in ('pip --version 2^>^&1') do echo ✅ pip found: %%i
)

echo.
if defined missing (
    echo ❌ SYSTEM CHECK FAILED
    echo Please install missing requirements and run this check again
    echo.
    echo Installation links:
    echo • Python: https://python.org/downloads
    echo • Node.js: https://nodejs.org/downloads
) else (
    echo ✅ SYSTEM CHECK PASSED
    echo Your system is ready for V47.14 Trading Bot!
    echo Run SETUP_WINDOWS.bat to continue setup.
)

echo.
pause