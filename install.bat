@echo off
SETLOCAL EnableDelayedExpansion

:: install.bat - KettleBrain installation (run from project directory)

:: --- Variables ---
SET "PROJECT_DIR=%~dp0"
IF %PROJECT_DIR:~-1%==\ SET "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

SET "VENV_DIR=%PROJECT_DIR%\venv"
SET "DATA_DIR=%USERPROFILE%\kettlebrain-data"
SET "SHORTCUT_PATH=%USERPROFILE%\Desktop\KettleBrain.lnk"
SET "ICON_PATH=%PROJECT_DIR%\src\assets\kettle.png"
SET "SCRIPT_PATH=%PROJECT_DIR%\src\main.py"

echo.
echo ==========================================
echo    KettleBrain Installer
echo ==========================================
echo Project: %PROJECT_DIR%
echo.

:: --- Step 1: Data Directory ---
echo --- [Step 1/3] Configuring Data Directory ---
IF NOT EXIST "%DATA_DIR%" (
    mkdir "%DATA_DIR%"
    echo Created data directory: %DATA_DIR%
) ELSE (
    echo Data directory exists.
)

:: --- Step 2: Python Environment ---
echo.
echo --- [Step 2/3] Setting up Python Environment ---
IF EXIST "%VENV_DIR%" (
    echo Virtual environment exists. Skipping creation.
) ELSE (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
)

IF %ERRORLEVEL% NEQ 0 (
    echo [FATAL ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo Installing dependencies...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV_DIR%\Scripts\python.exe" -m pip install -r "%PROJECT_DIR%\requirements.txt"

IF %ERRORLEVEL% NEQ 0 (
    echo [FATAL ERROR] Dependency installation failed.
    pause
    exit /b 1
)

:: --- Step 3: Desktop Shortcut ---
echo.
echo --- [Step 3/3] Creating Desktop Shortcut ---
:: Windows shortcuts need .ico format; convert PNG to ICO using Pillow (Kivy dependency)
SET "ICON_ICO=%PROJECT_DIR%\src\assets\kettle.ico"
"%VENV_DIR%\Scripts\python.exe" -c "from PIL import Image; img=Image.open(r'%ICON_PATH%'); img=img.convert('RGBA'); img.save(r'%ICON_ICO%', format='ICO', sizes=[(256,256),(48,48),(32,32),(16,16)])" 2>nul
IF EXIST "%ICON_ICO%" (
    SET "SHORTCUT_ICON=%ICON_ICO%"
) ELSE (
    SET "SHORTCUT_ICON=%ICON_PATH%"
)

SET "TARGET=%VENV_DIR%\Scripts\pythonw.exe"
SET "ARGS=\"%SCRIPT_PATH%\""

powershell -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut('%SHORTCUT_PATH%');$s.TargetPath='%TARGET%';$s.Arguments='%ARGS%';$s.WorkingDirectory='%PROJECT_DIR%\src';$s.IconLocation='!SHORTCUT_ICON!';$s.Save()"

echo Shortcut created on Desktop: KettleBrain.lnk

echo.
echo ==========================================
echo    Installation complete!
echo ==========================================
echo.
echo Run KettleBrain from the Desktop shortcut or:
echo   %VENV_DIR%\Scripts\pythonw.exe "%SCRIPT_PATH%"
echo.
pause
