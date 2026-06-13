#!/usr/bin/env bash
# Junior Aladdin — Setup Script
# Usage: bash scripts/setup.sh
#
# Creates a virtual environment, installs dependencies, and prompts for .env setup.

set -e

echo "========================================"
echo " Junior Aladdin — Setup"
echo "========================================"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "[1/3] Creating virtual environment..."
    python3 -m venv venv
else
    echo "[1/3] Virtual environment already exists."
fi

# Activate virtual environment
source venv/bin/activate

# Install package in editable mode
echo "[2/3] Installing package and dependencies..."
pip install -e ".[dev]"

# Check for .env file
if [ ! -f ".env" ]; then
    echo "[3/3] Creating .env from .env.example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo ""
        echo "========================================"
        echo " IMPORTANT: Edit .env with your"
        echo " Angel One API credentials before"
        echo " running the system."
        echo "========================================"
    else
        echo "WARNING: .env.example not found. Create .env manually."
    fi
else
    echo "[3/3] .env already exists. Skipping."
fi

echo ""
echo "========================================"
echo " Setup complete!"
echo " Run tests:  pytest tests/"
echo " Activate:   source venv/bin/activate"
echo "========================================"
