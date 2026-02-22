#!/bin/bash
# RadSim Uninstaller

echo "Uninstalling RadSim..."

# Remove the pip-installed package
pip uninstall radsim -y 2>/dev/null || python3 -m pip uninstall radsim -y 2>/dev/null || true
echo "[OK] Package removed"

# Remove config directory (~/.radsim/)
if [[ -d "$HOME/.radsim" ]]; then
    rm -rf "$HOME/.radsim"
    echo "[OK] Config directory removed (~/.radsim/)"
fi

echo ""
echo "RadSim has been uninstalled."
echo ""
