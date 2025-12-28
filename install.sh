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

# File Paths
KB_TEMPLATE="$PROJECT_DIR/kettlebrain.desktop"
KB_INSTALL_LOC="$HOME/.local/share/applications/kettlebrain.desktop"

# We don't assume a template exists for WaterBrain yet, but we define the path just in case
WB_TEMPLATE="$PROJECT_DIR/waterbrain.desktop"
WB_INSTALL_LOC="$HOME/.local/share/applications/waterbrain.desktop"

DATA_DIR="$HOME/kettlebrain-data"
TEMP_DESKTOP_FILE="/tmp/kettlebrain_temp.desktop"

echo "Project path: $PROJECT_DIR"

# --- 2. Install System Dependencies ---
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
mkdir -p "$HOME/.local/share/applications"

# ==========================================
# 6A. KETTLEBRAIN SHORTCUT (Restored Logic)
# ==========================================
if [ -f "$KB_TEMPLATE" ]; then
    echo "Using existing KettleBrain template..."
    cp "$KB_TEMPLATE" "$TEMP_DESKTOP_FILE"
    
    # Inject paths (Original logic)
    EXEC_CMD="$VENV_PYTHON_EXEC $PROJECT_DIR/src/main.py"
    ICON_PATH="$PROJECT_DIR/src/assets/kettle.png"
    
    sed -i "s|Exec=PLACEHOLDER_EXEC_PATH|Exec=$EXEC_CMD|g" "$TEMP_DESKTOP_FILE"
    sed -i "s|Path=PLACEHOLDER_PATH|Path=$PROJECT_DIR|g" "$TEMP_DESKTOP_FILE"
    sed -i "s|Icon=PLACEHOLDER_ICON_PATH|Icon=$ICON_PATH|g" "$TEMP_DESKTOP_FILE"
    
    mv "$TEMP_DESKTOP_FILE" "$KB_INSTALL_LOC"
else
    echo "Creating default KettleBrain shortcut (No Utility category)..."
    # Note: Removed 'Utility' to ensure it goes to 'Other'
    cat <<EOF > "$KB_INSTALL_LOC"
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
Categories=Application;
StartupWMClass=KettleBrain
EOF
fi
chmod +x "$KB_INSTALL_LOC"
echo " - KettleBrain Installed"

# ==========================================
# 6B. WATERBRAIN SHORTCUT (New Logic)
# ==========================================
# We use the same logic: Check for template, else generate default.
if [ -f "$WB_TEMPLATE" ]; then
    echo "Using existing WaterBrain template..."
    cp "$WB_TEMPLATE" "$TEMP_DESKTOP_FILE"
    
    EXEC_CMD="$VENV_PYTHON_EXEC $PROJECT_DIR/src/main_water.py"
    ICON_PATH="$PROJECT_DIR/src/assets/water-drop.png"
    
    sed -i "s|Exec=PLACEHOLDER_EXEC_PATH|Exec=$EXEC_CMD|g" "$TEMP_DESKTOP_FILE"
    sed -i "s|Path=PLACEHOLDER_PATH|Path=$PROJECT_DIR|g" "$TEMP_DESKTOP_FILE"
    sed -i "s|Icon=PLACEHOLDER_ICON_PATH|Icon=$ICON_PATH|g" "$TEMP_DESKTOP_FILE"
    
    mv "$TEMP_DESKTOP_FILE" "$WB_INSTALL_LOC"
else
    echo "Creating default WaterBrain shortcut (No Utility category)..."
    # We use 'Application;' category to force it into 'Other'
    cat <<EOF > "$WB_INSTALL_LOC"
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
Categories=Application;
StartupWMClass=WaterBrain
EOF
fi
chmod +x "$WB_INSTALL_LOC"
echo " - WaterBrain Installed"

# Force menu refresh
update-desktop-database "$HOME/.local/share/applications" || true

echo ""
echo "================================================="
echo "Installation complete!"
echo "Check the 'Other' menu for your apps."
echo "================================================="
exit 0
