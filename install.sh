#!/bin/bash
# RadSim Installer for macOS and Linux
# Install: curl -fsSL https://raw.githubusercontent.com/MBemera/Radsim/main/install.sh | bash
# Usage: ./install.sh

set -e

# Display banner
echo ""
echo "  +-------------------------------------+"
echo "  |         RadSim Installer            |"
echo "  |   Radically Simple Code Generator   |"
echo "  +-------------------------------------+"
echo ""

# Check for python3
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PY_VERSION=$(python -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo "2")
    if [[ "$PY_VERSION" == "3" ]]; then
        PYTHON_CMD="python"
    fi
fi

if [[ -z "$PYTHON_CMD" ]]; then
    echo "[ERROR] Python 3 is required but not found."
    echo ""
    echo "Please install Python 3.10 or higher:"
    echo ""
    echo "  macOS:   brew install python@3.12"
    echo "  Ubuntu:  sudo apt install python3 python3-pip"
    echo "  Fedora:  sudo dnf install python3 python3-pip"
    echo ""
    exit 1
fi

# Check Python version
PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 10 ]]; then
    echo "[ERROR] Python 3.10 or higher is required. Found: Python $PYTHON_VERSION"
    echo ""
    echo "Please install a newer Python version:"
    echo ""
    echo "  macOS:   brew install python@3.12"
    echo "  Ubuntu:  sudo apt install python3.12"
    echo "  Fedora:  sudo dnf install python3.12"
    echo ""
    exit 1
fi

echo "[OK] Python $PYTHON_VERSION detected"

# Check for pip
PIP_CMD=""
if $PYTHON_CMD -m pip --version &> /dev/null; then
    PIP_CMD="$PYTHON_CMD -m pip"
elif command -v pip3 &> /dev/null; then
    PIP_CMD="pip3"
elif command -v pip &> /dev/null; then
    PIP_CMD="pip"
fi

if [[ -z "$PIP_CMD" ]]; then
    echo "[ERROR] pip is not installed."
    echo ""
    echo "Please install pip:"
    echo ""
    echo "  macOS:   brew install python@3.12  (includes pip)"
    echo "  Ubuntu:  sudo apt install python3-pip"
    echo "  Fedora:  sudo dnf install python3-pip"
    echo ""
    exit 1
fi

echo "[OK] pip available"

# Detect OS
OS="$(uname -s)"
case "$OS" in
    Darwin) OS_NAME="macOS" ;;
    Linux)  OS_NAME="Linux" ;;
    *)      OS_NAME="$OS" ;;
esac

echo "[OK] Platform: $OS_NAME ($(uname -m))"

# Check for existing configuration
RADSIM_CONFIG_DIR="$HOME/.radsim"
if [[ -d "$RADSIM_CONFIG_DIR" ]]; then
    echo ""
    echo "[!!] Existing RadSim configuration found at ~/.radsim/"
    echo ""
    echo "  Options:"
    echo "    1) Fresh install - remove old config and run setup again"
    echo "    2) Keep config   - preserve existing settings and API keys"
    echo ""
    read -r -p "  Choose [1/2] (default: 1): " CONFIG_CHOICE
    CONFIG_CHOICE="${CONFIG_CHOICE:-1}"

    if [[ "$CONFIG_CHOICE" == "1" ]]; then
        rm -rf "$RADSIM_CONFIG_DIR"
        echo "[OK] Old configuration removed. Setup will run on first launch."
    else
        echo "[OK] Keeping existing configuration."
    fi
fi

# Install radsim from PyPI
echo "[..] Installing RadSim from PyPI..."

$PIP_CMD install radsimcli --quiet

echo "[OK] RadSim installed"

# Verify the radsim command is available
if command -v radsim &> /dev/null; then
    echo "[OK] 'radsim' command is available"
else
    # pip --user installs to ~/.local/bin, make sure it's in PATH
    BIN_DIR="$HOME/.local/bin"

    SHELL_RC=""
    if [[ "$SHELL" == *"zsh"* ]]; then
        SHELL_RC="$HOME/.zshrc"
    elif [[ "$SHELL" == *"bash"* ]]; then
        if [[ "$OS" == "Darwin" ]] && [[ -f "$HOME/.bash_profile" ]]; then
            SHELL_RC="$HOME/.bash_profile"
        else
            SHELL_RC="$HOME/.bashrc"
        fi
    fi

    if [[ -n "$SHELL_RC" ]] && ! grep -q '.local/bin' "$SHELL_RC" 2>/dev/null; then
        echo '' >> "$SHELL_RC"
        echo '# RadSim' >> "$SHELL_RC"
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
        echo "[OK] Added ~/.local/bin to PATH in $(basename "$SHELL_RC")"
        PATH_UPDATED="yes"
    fi
fi

# Done
echo ""
echo "================================================"
echo "  RadSim installed successfully!"
echo "================================================"
echo ""
echo "To get started:"
echo ""

if [[ "$PATH_UPDATED" == "yes" ]]; then
    echo "  1. Restart your terminal (or run: source $SHELL_RC)"
    echo ""
fi

echo "  Run RadSim:"
echo "     radsim"
echo ""
echo "  On first run, RadSim will guide you through setup"
echo "  (provider selection, API key, preferences)."
echo ""
