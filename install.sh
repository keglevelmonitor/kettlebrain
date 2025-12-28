#!/bin/bash
# install.sh
# Installation script for KettleBrain AND WaterBrain.

# Stop on any error
set -e

echo "=========================================="
echo "    KettleBrain Suite Installer"
echo "=========================================="

# --- 1. Define Variables ---
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_EXEC="python3"
VENV_DIR="$PROJECT_DIR/venv"
VENV_PYTHON_EXEC="$VENV_DIR/bin/python"

# Desktop Entry Paths (KettleBrain)
KB_INSTALL_LOCATION="$HOME/.local/share/applications/kettlebrain.desktop"

# Desktop Entry Paths (WaterBrain)
WB_INSTALL_LOCATION="$HOME/.local/share/applications/waterbrain.desktop"

DATA_DIR="$HOME/kettlebrain-data"

echo "Project path: $PROJECT_DIR"

# --- 2. Install System Dependencies ---
# (No changes needed here - they share dependencies)
echo ""
echo "--- [Step 1/5] Checking System Dependencies ---"
sudo apt-get update
sudo apt-get install -y \
    python3-tk python3-dev swig python3-venv liblgpio-dev numlockx \
    libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev \
    libportmidi-dev libswscale-dev libavformat-dev libavcodec-dev \
    zlib1g-dev libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    libgstreamer1.0-0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    libmtdev-dev xclip xsel libjpeg-dev

# --- 3. Setup Python Environment ---
echo ""
echo "--- [Step 2/5] Setting up Virtual Environment ---"
# (No changes needed here - they share the venv)
if [ -d "$VENV_DIR" ]; then
    rm -rf "$VENV_DIR"
fi
$PYTHON_EXEC -m venv "$VENV_DIR" --system-site-packages

# --- 4. Install Python Libraries ---
echo ""
echo "--- [Step 3/5] Installing Python Libraries ---"
"$VENV_PYTHON_EXEC" -m pip install --upgrade pip setuptools wheel
if [ -f "$PROJECT_DIR/requirements.txt" ]; then
    "$VENV_PYTHON_EXEC" -m pip install -r "$PROJECT_DIR/requirements.txt"
else
    "$VENV_PYTHON_EXEC" -m pip install "kivy[base]" rpi-lgpio
fi

# --- 5. Create User Data Directory ---
echo ""
echo "--- [Step 4/5] Configuring Data Directory ---"
mkdir -p "$DATA_DIR"

# --- 6. Install Desktop Shortcuts ---
echo ""
echo "--- [Step 5/5] Installing Desktop Shortcuts ---"

# --- 6a. Install KettleBrain Shortcut ---
echo "Installing KettleBrain shortcut..."
cat <<EOF > "$KB_INSTALL_LOCATION"
[Desktop Entry]
Version=1.0
Type=Application
Name=KettleBrain
Comment=Raspberry Pi Brewing Controller
Path=$PROJECT_DIR
Exec=$VENV_PYTHON_EXEC $PROJECT_DIR/src/main.py
Icon=$PROJECT_DIR/src/assets/kettle.png
Terminal=false
StartupNotify=true
Categories=Utility;X-Other;
StartupWMClass=KettleBrain
EOF
chmod +x "$KB_INSTALL_LOCATION"

# --- 6b. Install WaterBrain Shortcut (NEW) ---
echo "Installing WaterBrain shortcut..."
cat <<EOF > "$WB_INSTALL_LOCATION"
[Desktop Entry]
Version=1.0
Type=Application
Name=WaterBrain
Comment=Water Chemistry Calculator
Path=$PROJECT_DIR
Exec=$VENV_PYTHON_EXEC $PROJECT_DIR/src/main_water.py
Icon=$PROJECT_DIR/src/assets/water-drop.png
Terminal=false
StartupNotify=true
Categories=Utility;X-Other;
StartupWMClass=WaterBrain
EOF
chmod +x "$WB_INSTALL_LOCATION"

# Force menu refresh
update-desktop-database "$HOME/.local/share/applications" || true

echo ""
echo "================================================="
echo "Installation complete!"
echo "Both KettleBrain and WaterBrain are available in the Utility menu."
echo "================================================="
exit 0
