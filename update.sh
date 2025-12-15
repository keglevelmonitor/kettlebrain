#!/bin/bash
# update.sh
# Handles pulling code AND dependency updates for KettleBrain.

# --- 1. Define Variables ---
# Get the full path to the directory this script is in (the project root)
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Define paths for the virtual environment
VENV_DIR="$PROJECT_DIR/venv"
VENV_PYTHON_EXEC="$VENV_DIR/bin/python"

echo "--- KettleBrain Update Script ---"
echo "Starting update in $PROJECT_DIR"

# --- 2. Check for Git Sanity ---
if [ ! -d "$PROJECT_DIR/.git" ]; then
    echo "[ERROR] This directory does not appear to be a Git repository."
    echo "Please ensure you run 'git clone' first."
    exit 1
fi

# --- 3. Run Git Pull ---
echo "--- Pulling latest code from git... ---"
git pull
if [ $? -ne 0 ]; then
    echo "[ERROR] 'git pull' failed. Check for local changes or branch conflicts."
    exit 1
fi
echo "--- Git pull complete ---"

# --- 4. Update System Dependencies ---
echo "Checking system-level dependencies (apt)..."
echo "You may be asked for your password."

sudo apt-get install -y python3-tk python3-dev swig python3-venv liblgpio-dev numlockx

if [ $? -ne 0 ]; then
    echo "[WARNING] System dependency check failed. The app might still work, but some features could be missing."
fi

# --- 5. Run Python Dependency Installation ---
echo "Checking for new Python dependencies..."

# Check if venv exists first
if [ ! -f "$VENV_PYTHON_EXEC" ]; then
    echo "[ERROR] Virtual environment not found at $VENV_PYTHON_EXEC"
    echo "This script only updates an existing installation."
    echo "Please run the ./install.sh script first."
    exit 1
fi

# Install packages using the venv's pip
"$VENV_PYTHON_EXEC" -m pip install -r "$PROJECT_DIR/requirements.txt"

# Check if pip installation succeeded
if [ $? -ne 0 ]; then
    echo "[FATAL ERROR] Dependency update failed. Check internet connection or requirements.txt."
    exit 1
fi

echo "--- Dependency Update Complete ---"
echo "--- Please close and restart the KettleBrain application ---"
