#!/bin/bash
# install.sh
# Installation script for KettleBrain application.

# Stop on any error to prevent broken installs
set -e

echo "=========================================="
echo "   KettleBrain Installer"
echo "=========================================="

# --- 1. Define Variables ---
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_EXEC="python3"
VENV_DIR="$PROJECT_DIR/venv"
VENV_PYTHON_EXEC="$VENV_DIR/bin/python"

# Desktop Entry Paths
DESKTOP_FILE_TEMPLATE="$PROJECT_DIR/kettlebrain.desktop"
# Note: We force lowercase here to match standard conventions
INSTALL_LOCATION="$HOME/.local/share/applications/kettlebrain.desktop"
DATA_DIR="$HOME/kettlebrain-data"
# Temp file for modification
TEMP_DESKTOP_FILE="/tmp/kettlebrain_temp.desktop"

echo "Project path: $PROJECT_DIR"

# --- 2. Install System Dependencies (Requires Sudo) ---
echo ""
echo "--- [Step 1/5] Checking System Dependencies ---"
echo "You may be asked for your password to install system packages."

# Install Tkinter, Build Tools (swig/dev), GPIO C-Library (liblgpio-dev), AND numlockx
sudo apt-get update
sudo apt-get install -y python3-tk python3-dev swig python3-venv liblgpio-dev numlockx

# --- 3. Setup Python Environment (Clean Install) ---
echo ""
echo "--- [Step 2/5] Setting up Virtual Environment ---"

# CLEANUP: Delete existing venv to ensure a clean slate
if [ -d "$VENV_DIR" ]; then
    echo "Removing old virtual environment for a clean install..."
    rm -rf "$VENV_DIR"
fi

echo "Creating new Python virtual environment at $VENV_DIR..."
$PYTHON_EXEC -m venv "$VENV_DIR"

if [ $? -ne 0 ]; then
    echo "[FATAL ERROR] Failed to create virtual environment."
    exit 1
fi

# --- 4. Install Python Libraries ---
echo ""
echo "--- [Step 3/5] Installing Python Libraries ---"

# Upgrade pip inside the venv
"$VENV_PYTHON_EXEC" -m pip install --upgrade pip

# Install dependencies using the pip INSIDE the virtual environment
if [ -f "$PROJECT_DIR/requirements.txt" ]; then
    echo "Installing from requirements.txt..."
    "$VENV_PYTHON_EXEC" -m pip install -r "$PROJECT_DIR/requirements.txt"
else
    echo "WARNING: requirements.txt not found. Installing default shim (rpi-lgpio)..."
    # Fallback for KettleBrain if requirements file is missing
    "$VENV_PYTHON_EXEC" -m pip install rpi-lgpio
fi

if [ $? -ne 0 ]; then
    echo "[FATAL ERROR] Dependency installation failed."
    exit 1
fi

# --- 5. Create User Data Directory ---
echo ""
echo "--- [Step 4/5] Configuring Data Directory ---"
if [ ! -d "$DATA_DIR" ]; then
    echo "Creating user data directory: $DATA_DIR"
    mkdir -p "$DATA_DIR"
    chmod 700 "$DATA_DIR"
else
    echo "Data directory already exists ($DATA_DIR). Skipping."
fi

# --- 6. Install Desktop Shortcut ---
echo ""
echo "--- [Step 5/5] Installing Desktop Shortcut ---"

if [ -f "$DESKTOP_FILE_TEMPLATE" ]; then
    # 6a. Prepare paths
    # EXEC_CMD points to the VENV python to ensure libraries are found
    EXEC_CMD="$VENV_PYTHON_EXEC $PROJECT_DIR/src/main.py"
    
    # Updated Icon Path for KettleBrain
    ICON_PATH="$PROJECT_DIR/src/assets/kettle.png"
    
    # 6b. Create the modified file in /tmp
    cp "$DESKTOP_FILE_TEMPLATE" "$TEMP_DESKTOP_FILE"
    
    # 6c. Inject correct paths
    sed -i "s|Exec=PLACEHOLDER_EXEC_PATH|Exec=$EXEC_CMD|g" "$TEMP_DESKTOP_FILE"
    sed -i "s|Path=PLACEHOLDER_PATH|Path=$PROJECT_DIR/src|g" "$TEMP_DESKTOP_FILE"
    sed -i "s|Icon=PLACEHOLDER_ICON_PATH|Icon=$ICON_PATH|g" "$TEMP_DESKTOP_FILE"
    
    # 6d. Install to Application Menu (System Menu)
    mkdir -p "$HOME/.local/share/applications"
    mv "$TEMP_DESKTOP_FILE" "$INSTALL_LOCATION"
    chmod +x "$INSTALL_LOCATION"
    echo "Shortcut installed to Application Menu: $INSTALL_LOCATION"

else
    echo "[WARNING] kettlebrain.desktop template not found. Skipping shortcut."
fi

echo ""
echo "================================================="
echo ""
echo "Installation complete!"
echo ""
echo "At the Applications menu:"
echo "   select Other > KettleBrain to run the app."
echo ""
echo "================================================="
echo ""

read -p "Enter Y to launch KettleBrain, or any other key to exit: " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Launching KettleBrain..."
    # Launch in background, detached from terminal
    nohup "$VENV_PYTHON_EXEC" "$PROJECT_DIR/src/main.py" >/dev/null 2>&1 &
    disown
    
    # Attempt to close the terminal window/session
    kill -HUP $PPID
    exit 0
else
    echo "Exiting installer."
    exit 0
fi
