#!/bin/bash
# uninstall.sh
# Uninstallation script for KettleBrain & WaterBrain

APP_DIR="$HOME/kettlebrain"
DATA_DIR="$HOME/kettlebrain-data"

# Define both shortcut paths
KB_DESKTOP_FILE="$HOME/.local/share/applications/kettlebrain.desktop"
WB_DESKTOP_FILE="$HOME/.local/share/applications/waterbrain.desktop"

clear
echo "=========================================="
echo "    KettleBrain Suite Uninstaller"
echo "=========================================="
echo "Please choose an option (Case Sensitive):"
echo "  APP  - Uninstall ONLY the application."
echo "  ALL  - Uninstall the application AND all data."
echo ""
read -p "Enter your choice (APP or ALL): " choice

if [ "$choice" == "APP" ]; then
    TO_DELETE="$APP_DIR"
elif [ "$choice" == "ALL" ]; then
    TO_DELETE="$APP_DIR and $DATA_DIR"
else
    exit 0
fi

echo "------------------------------------------"
echo "YOU ARE ABOUT TO DELETE:"
echo "$TO_DELETE"
echo "------------------------------------------"
read -p "Type YES to confirm: " confirm

if [ "$confirm" != "YES" ]; then
    echo "Cancelled."
    exit 0
fi

echo "Removing files..."

# 1. Remove Desktop Shortcuts
if [ -f "$KB_DESKTOP_FILE" ]; then
    rm "$KB_DESKTOP_FILE"
    echo " - Removed KettleBrain shortcut"
fi

if [ -f "$WB_DESKTOP_FILE" ]; then
    rm "$WB_DESKTOP_FILE"
    echo " - Removed WaterBrain shortcut"
fi

# 2. Remove App Directory
if [ -d "$APP_DIR" ]; then
    rm -rf "$APP_DIR"
    echo " - Removed application directory"
fi

# 3. Remove Data Directory
if [ "$choice" == "ALL" ] && [ -d "$DATA_DIR" ]; then
    rm -rf "$DATA_DIR"
    echo " - Removed data directory"
fi

# 4. Remove AutoStart
if [ -f "$HOME/.config/autostart/kettlebrain.desktop" ]; then
    rm "$HOME/.config/autostart/kettlebrain.desktop"
    echo " - Removed auto-start configuration"
fi

echo "Uninstallation Complete"
