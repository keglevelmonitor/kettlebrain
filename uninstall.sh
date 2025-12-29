#!/bin/bash
# uninstall.sh
# Uninstallation script for KettleBrain

APP_DIR="$HOME/kettlebrain"
DATA_DIR="$HOME/kettlebrain-data"

# Define shortcut path
KB_DESKTOP_FILE="$HOME/.local/share/applications/kettlebrain.desktop"

clear
echo "=========================================="
echo "    KettleBrain Uninstaller"
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

# 1. Remove Desktop Shortcut
if [ -f "$KB_DESKTOP_FILE" ]; then
    rm "$KB_DESKTOP_FILE"
    echo " - Removed KettleBrain shortcut"
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

echo ""
echo "Uninstallation Complete."
