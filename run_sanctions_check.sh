#!/bin/bash

################################################################################
# Sanctions Check Program - Mac/Linux Deployment Script
################################################################################
#
# This script simplifies deployment for Mac and Linux users:
# 1. Checks Python installation
# 2. Installs required packages
# 3. Runs sanctions checker
# 4. No manual environment setup needed
#
# Usage: chmod +x run_sanctions_check.sh && ./run_sanctions_check.sh
#
################################################################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Header
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  SANCTIONS CHECK PROGRAM - Mac/Linux Deployment Suite     ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Timestamp: $(date)"
echo "Hostname: $(hostname)"
echo "User: $(whoami)"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR] Python 3 is not installed${NC}"
    echo ""
    echo "Please install Python 3:"
    echo ""
    echo "For Mac (using Homebrew):"
    echo "  brew install python3"
    echo ""
    echo "For Ubuntu/Debian:"
    echo "  sudo apt-get install python3 python3-pip"
    echo ""
    echo "For Fedora/RHEL:"
    echo "  sudo dnf install python3 python3-pip"
    echo ""
    exit 1
fi

echo -e "${GREEN}[✓] Python 3 detected${NC}"
python3 --version

echo ""
echo "Installing required packages..."
echo "This may take 2-3 minutes..."
echo ""

# Create virtual environment (recommended)
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip 2>/dev/null

# Install packages
pip install pandas selenium webdriver-manager python-docx pillow 2>/dev/null

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] Failed to install packages${NC}"
    exit 1
fi

echo -e "${GREEN}[✓] All packages installed successfully${NC}"

echo ""
echo "Starting Sanctions Check Program..."
echo ""

# Run the Python script
python3 sanctions_checker_improved.py

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║        Sanctions Check Complete                            ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Results saved to: results/ folder"
echo "Audit log: results/audit_log_*.csv"
echo ""

# Deactivate virtual environment
deactivate
