#!/bin/bash
# setup.sh
# Single-line installer wrapper for KettleBrain

# 1. Define the Install Directories
INSTALL_DIR="$HOME/kettlebrain"
DATA_DIR="$HOME/kettlebrain-data"
WHAT_TO_INSTALL="KettleBrain Application and Data Directory"
CLEANUP_MODE="NONE"

echo "========================================"
echo "    KettleBrain Auto-Installer"
echo "========================================"

# 2. Logic to handle existing installs
if [ -d "$INSTALL_DIR" ] || [ -d "$DATA_DIR" ]; then
    echo ""
    echo "Existing installation detected:"
    [ -d "$INSTALL_DIR" ] && echo " - App Folder: $INSTALL_DIR"
    [ -d "$DATA_DIR" ]    && echo " - Data Folder: $DATA_DIR"
    echo ""
    echo "How would you like to proceed? (Case Sensitive)"
    echo "  APP  - Reinstall App only (Keeps your existing data/settings)"
    echo "  ALL  - Reinstall App AND reset data (Fresh Install)"
    echo "  EXIT - Cancel installation"
    echo ""
    read -p "Enter selection: " choice
    
    if [ "$choice" == "APP" ]; then
        WHAT_TO_INSTALL="KettleBrain Application"
        CLEANUP_MODE="APP"
    elif [ "$choice" == "ALL" ]; then
        WHAT_TO_INSTALL="KettleBrain Application and Data Directory"
        CLEANUP_MODE="ALL"
    else
        echo "Cancelled."
        exit 0
    fi
fi

# 3. Size Warning / Confirmation
echo ""
echo "------------------------------------------------------------"
echo "This script will install the $WHAT_TO_INSTALL"
echo "and will use about 350 MB of storage space (inc. Kivy deps)."
echo "------------------------------------------------------------"
echo ""

read -p "Press Y to proceed, or any other key to cancel: " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Installation cancelled."
    exit 1
fi

# 4. Perform Cleanup
if [ "$CLEANUP_MODE" == "APP" ]; then
    echo "Removing existing application..."
    rm -rf "$INSTALL_DIR"
elif [ "$CLEANUP_MODE" == "ALL" ]; then
    echo "Removing application and data..."
    rm -rf "$INSTALL_DIR"
    rm -rf "$DATA_DIR"
fi

# 5. Check/Install Git
if ! command -v git &> /dev/null; then
    echo "Git not found. Installing..."
    sudo apt-get update && sudo apt-get install -y git
fi

# 6. Clone Repo
if [ -d "$INSTALL_DIR" ]; then
    echo "Directory exists (Update mode)..."
    cd "$INSTALL_DIR" || exit 1
    git pull
else
    echo "Cloning repository to $INSTALL_DIR..."
    git clone https://github.com/keglevelmonitor/kettlebrain.git "$INSTALL_DIR"
    cd "$INSTALL_DIR" || exit 1
fi

# 7. Run the Main Installer
echo "Launching main installer..."
chmod +x install.sh
./install.sh
