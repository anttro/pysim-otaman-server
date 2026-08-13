@echo off
REM pysim-otaman-server setup script for Windows
REM Creates a venv and installs pysim and its dependencies.

setlocal enabledelayedexpansion

set VENV_DIR=%~dp0.venv

echo === pysim-otaman-server setup ===
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is required but not found.
    echo Install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

echo Found Python
python --version

REM Check Git
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Git is required but not found.
    echo Install Git from https://git-scm.com
    pause
    exit /b 1
)

echo Found Git
git --version
echo.

REM Create venv
if not exist "%VENV_DIR%" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
)
call "%VENV_DIR%\Scripts\activate.bat"

REM Upgrade pip
python -m pip install --upgrade pip -q

REM Install pysim
echo === Installing pysim ===
pip install git+https://github.com/osmocom/pysim.git
if %errorlevel% neq 0 (
    echo Error: Failed to install pysim.
    pause
    exit /b 1
)
echo.

REM Install pysim-otaman-server
echo === Installing pysim-otaman-server ===
pip install -e "%~dp0"
if %errorlevel% neq 0 (
    echo Error: Failed to install pysim-otaman-server.
    pause
    exit /b 1
)
echo.

echo === Setup complete ===
echo Run start.bat to start the server.
pause