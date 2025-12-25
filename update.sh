#!/bin/bash
# update.sh
# Handles pulling code AND dependency updates for KettleBrain.

# --- 1. Define Variables ---
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
VENV_PYTHON_EXEC="$VENV_DIR/bin/python"

# --- 2. Check Mode ---
# If passed "--check", we only run git fetch and compare
if [ "$1" == "--check" ]; then
    echo "Checking for updates..."
    cd "$PROJECT_DIR"
    git fetch
    
    LOCAL=$(git rev-parse @)
    REMOTE=$(git rev-parse @{u})
    
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "Update Available!"
        echo "Local: $LOCAL"
        echo "Remote: $REMOTE"
        exit 0 # Success (updates exist)
    else
        echo "System is up to date."
        exit 1 # Fail (no updates)
    fi
fi

echo "--- KettleBrain Update Script ---"
echo "Starting update in $PROJECT_DIR"

# --- 3. Check for Git Sanity ---
if [ ! -d "$PROJECT_DIR/.git" ]; then
    echo "[ERROR] This directory does not appear to be a Git repository."
    exit 1
fi

# --- 4. Run Git Pull ---
echo "--- Pulling latest code from git... ---"
git pull
if [ $? -ne 0 ]; then
    echo "[ERROR] 'git pull' failed. Check for local changes."
    exit 1
fi

# --- 5. Update System Dependencies ---
echo "Verifying system dependencies..."
sudo apt-get install -y \
    python3-tk python3-dev swig python3-venv liblgpio-dev numlockx \
    libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev \
    libportmidi-dev libswscale-dev libavformat-dev libavcodec-dev \
    zlib1g-dev libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    libgstreamer1.0-0 gstreamer1.0-plugins-base \
    libmtdev-dev xclip xsel libjpeg-dev

# --- 6. Run Python Dependency Installation ---
echo "Checking for new Python dependencies..."

if [ ! -f "$VENV_PYTHON_EXEC" ]; then
    echo "[ERROR] Virtual environment missing. Please run install.sh."
    exit 1
fi

"$VENV_PYTHON_EXEC" -m pip install -r "$PROJECT_DIR/requirements.txt"

if [ $? -ne 0 ]; then
    echo "[FATAL ERROR] Dependency update failed."
    exit 1
fi

echo "--- Update Complete ---"
echo "Please restart the application."
