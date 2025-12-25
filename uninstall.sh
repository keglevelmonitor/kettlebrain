#!/bin/bash
# uninstall.sh
# Uninstallation script for KettleBrain

APP_DIR="$HOME/kettlebrain"
DATA_DIR="$HOME/kettlebrain-data"
DESKTOP_FILE="$HOME/.local/share/applications/kettlebrain.desktop"

# Clear screen for readability
clear

echo "=========================================="
echo "      KettleBrain Uninstaller"
echo "=========================================="
echo ""
echo "Please choose an option (Case Sensitive):"
echo ""
echo "  APP  - Uninstall ONLY the application."
echo "         (Deletes $APP_DIR)"
echo "         (Keeps your data and settings)"
echo ""
echo "  ALL  - Uninstall the application AND all data."
echo "         (Deletes $APP_DIR)"
echo "         (Deletes $DATA_DIR)"
echo ""
echo "Press any other key to exit without changes."
echo ""
read -p "Enter your choice (APP or ALL): " choice
echo ""

if [ "$choice" == "APP" ]; then
    TO_DELETE="$APP_DIR"
    MSG="The KettleBrain application folder."
elif [ "$choice" == "ALL" ]; then
    TO_DELETE="$APP_DIR and $DATA_DIR"
    MSG="The KettleBrain application AND all user data/settings."
else
    echo "Exiting without changes."
    exit 0
fi

echo "------------------------------------------"
echo "YOU ARE ABOUT TO DELETE:"
echo "$MSG"
echo "------------------------------------------"
echo ""
read -p "Type YES to confirm uninstallation: " confirm

if [ "$confirm" != "YES" ]; then
    echo "Confirmation failed. Exiting."
    exit 0
fi

echo ""
echo "Removing files..."

# 1. Remove Desktop Shortcut
if [ -f "$DESKTOP_FILE" ]; then
    rm "$DESKTOP_FILE"
    echo " - Removed desktop shortcut"
fi

# 2. Remove App Directory
if [ -d "$APP_DIR" ]; then
    rm -rf "$APP_DIR"
    echo " - Removed application directory: $APP_DIR"
else
    echo " - Application directory not found (already removed?)"
fi

# 3. Remove Data Directory
if [ "$choice" == "ALL" ]; then
    if [ -d "$DATA_DIR" ]; then
        rm -rf "$DATA_DIR"
        echo " - Removed data directory: $DATA_DIR"
    else
        echo " - Data directory not found."
    fi
fi

# 4. Remove AutoStart File (if exists)
AUTOSTART_FILE="$HOME/.config/autostart/kettlebrain.desktop"
if [ -f "$AUTOSTART_FILE" ]; then
    rm "$AUTOSTART_FILE"
    echo " - Removed auto-start configuration"
fi

echo ""
echo "=========================================="
echo "   Uninstallation Complete"
echo "=========================================="
