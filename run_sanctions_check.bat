@echo off
REM ============================================================
REM Sanctions Check Program - Windows Batch Deployment
REM ============================================================
REM 
REM This batch file simplifies deployment:
REM 1. Checks Python installation
REM 2. Installs required packages
REM 3. Runs sanctions checker
REM 4. No manual environment setup needed
REM
REM Usage: Double-click this file or run from command prompt
REM ============================================================

setlocal enabledelayedexpansion
color 0A
title Sanctions Check Automation

echo.
echo ============================================================
echo    SANCTIONS CHECK PROGRAM - Windows Deployment Suite
echo ============================================================
echo.
echo Time: %date% %time%
echo Computer: %COMPUTERNAME%
echo User: %USERNAME%
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo.
    echo Please download and install Python from:
    echo https://www.python.org/downloads/
    echo.
    echo Make sure to CHECK: "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo [✓] Python detected
python --version

echo.
echo Installing required packages...
echo This may take 2-3 minutes...
echo.

REM Install packages
pip install --upgrade pip >nul 2>&1
pip install pandas selenium webdriver-manager python-docx pillow pywin32 >nul 2>&1

if errorlevel 1 (
    echo [ERROR] Failed to install packages
    pause
    exit /b 1
)

echo [✓] All packages installed successfully

echo.
echo Starting Sanctions Check Program...
echo.

REM Run the Python script
python sanctions_checker_improved.py

echo.
echo ============================================================
echo    Sanctions Check Complete
echo ============================================================
echo.
echo Results saved to: results\ folder
echo Audit log: results\audit_log_*.csv
echo.
pause
