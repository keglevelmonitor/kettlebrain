@echo off
SETLOCAL EnableDelayedExpansion

:: setup.bat - Bootstrap installer for KettleBrain (Windows)
:: Can be run from anywhere (e.g. after: curl -sL ... -o setup.bat ^&^& setup.bat)
:: Clones repo to %USERPROFILE%\kettlebrain and runs install.bat

SET "INSTALL_DIR=%USERPROFILE%\kettlebrain"
SET "REPO_URL=https://github.com/keglevelmonitor/kettlebrain.git"

TITLE KettleBrain Auto-Installer

echo.
echo ========================================
echo    KettleBrain Windows Installer
echo ========================================
echo.

:: 1. Check if Git and Python are installed
where git >nul 2>nul
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Git is not installed. Please install Git for Windows:
    echo         https://git-scm.com/download/win
    pause
    exit /b 1
)
where python >nul 2>nul
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed. Please install Python from python.org
    echo         and check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: 2. Clone or update
IF EXIST "%INSTALL_DIR%" (
    echo Existing installation detected at:
    echo %INSTALL_DIR%
    echo.
    echo Updating code...
    cd /d "%INSTALL_DIR%"
    git pull
) ELSE (
    echo Cloning repository to %INSTALL_DIR%...
    git clone %REPO_URL% "%INSTALL_DIR%"
    cd /d "%INSTALL_DIR%"
)

IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Git operation failed.
    pause
    exit /b 1
)

:: 3. Run the main installer
echo.
echo Launching main installer...
call install.bat

echo.
echo ========================================
echo    Setup Complete!
echo ========================================
pause
