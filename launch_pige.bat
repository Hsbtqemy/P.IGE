@echo off
REM ============================================================================
REM PIGE Launcher - Batch Entry Point
REM ============================================================================
REM This simple batch file calls the PowerShell script that does all the work.
REM Double-click this file to launch PIGE.
REM ============================================================================

SETLOCAL

REM Get the directory where this batch file is located
SET SCRIPT_DIR=%~dp0

REM Call PowerShell script with ExecutionPolicy Bypass (no admin needed)
REM -NoProfile: Don't load user profile (faster startup)
REM -ExecutionPolicy Bypass: Allow script execution without changing system policy
REM %*: Pass all command-line arguments to PowerShell script

echo.
echo ============================================
echo    PIGE Launcher
echo ============================================
echo.
echo Initializing, please wait...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%launch_pige.ps1" %*

REM Check exit code
IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo ============================================
    echo    Launch failed with error code: %ERRORLEVEL%
    echo ============================================
    echo.
    echo Check the log file at:
    echo %LOCALAPPDATA%\PIGE\launcher.log
    echo.
    pause
    exit /b %ERRORLEVEL%
)

REM Success - don't pause on success to avoid extra window
exit /b 0