#!/usr/bin/env bash
# RadSim Uninstaller

set -uo pipefail

PACKAGE_NAME="radsimcli"

echo "Uninstalling RadSim..."

# Remove RadSim however it was installed: pipx first, then pip fallbacks.
if command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q "$PACKAGE_NAME"; then
    pipx uninstall "$PACKAGE_NAME" && echo "[OK] Package removed (pipx)"
else
    pip uninstall "$PACKAGE_NAME" -y 2>/dev/null \
        || python3 -m pip uninstall "$PACKAGE_NAME" -y 2>/dev/null \
        || true
    echo "[OK] Package removed"
fi

# Remove config directory (~/.radsim/) only after explicit confirmation.
if [[ -d "$HOME/.radsim" ]]; then
    read -r -p "Also remove config and API keys at ~/.radsim/? [y/N]: " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        rm -rf "$HOME/.radsim"
        echo "[OK] Config directory removed (~/.radsim/)"
    else
        echo "[OK] Kept config directory (~/.radsim/)"
    fi
fi

echo ""
echo "RadSim has been uninstalled."
echo ""
