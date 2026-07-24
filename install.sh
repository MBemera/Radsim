#!/usr/bin/env bash
# RadSim Installer for macOS and Linux.
#
# Installs the `radsim` CLI with pipx, which keeps RadSim in its own isolated
# environment. That avoids the "externally-managed-environment" error (PEP 668)
# that modern distros — Ubuntu/Debian, Fedora, Arch, openSUSE — raise when you
# pip-install into the system Python, and it never touches system packages.
#
# Install:  curl -fsSL https://raw.githubusercontent.com/MBemera/Radsim/main/install.sh | bash
# Or:       ./install.sh

set -euo pipefail

PACKAGE_NAME="radsimcli"
MIN_PYTHON_MINOR=10   # RadSim requires Python 3.10 or newer.
PYTHON_CMD=""
PIPX_CMD=""

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

print_banner() {
    echo ""
    echo "  +-------------------------------------+"
    echo "  |         RadSim Installer            |"
    echo "  |   Radically Simple Code Generator   |"
    echo "  +-------------------------------------+"
    echo ""
}

say_ok()   { printf '[OK] %s\n' "$1"; }
say_info() { printf '[..] %s\n' "$1"; }
say_warn() { printf '[!!] %s\n' "$1"; }
say_err()  { printf '[ERROR] %s\n' "$1" >&2; }

# Ask a yes/no question. Reads from the terminal so it also works under
# `curl | bash`. Non-interactive shells fail closed (treated as "no").
confirm() {
    local prompt="$1"
    local answer=""
    if [[ -r /dev/tty ]]; then
        read -r -p "  $prompt [y/N]: " answer < /dev/tty || answer=""
    else
        return 1
    fi
    [[ "$answer" =~ ^[Yy]$ ]]
}

# ---------------------------------------------------------------------------
# Platform and package-manager detection
# ---------------------------------------------------------------------------

detect_package_manager() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        command -v brew >/dev/null 2>&1 && echo "brew"
        return 0
    fi
    local manager
    for manager in apt-get dnf pacman zypper apk yum; do
        if command -v "$manager" >/dev/null 2>&1; then
            echo "$manager"
            return 0
        fi
    done
}

distro_name() {
    if [[ -r /etc/os-release ]]; then
        ( . /etc/os-release && echo "${PRETTY_NAME:-${NAME:-Linux}}" )
    else
        uname -s
    fi
}

python_package_for() {
    case "$1" in
        pacman) echo "python python-pip" ;;
        apk)    echo "python3 py3-pip" ;;
        brew)   echo "python" ;;
        *)      echo "python3 python3-pip" ;;
    esac
}

pipx_package_for() {
    case "$1" in
        pacman) echo "python-pipx" ;;
        zypper) echo "python3-pipx" ;;
        *)      echo "pipx" ;;
    esac
}

# The human-readable install command, used for guidance messages only.
install_command_for() {
    local manager="$1" packages="$2"
    case "$manager" in
        apt-get) echo "sudo apt-get install -y $packages" ;;
        dnf)     echo "sudo dnf install -y $packages" ;;
        yum)     echo "sudo yum install -y $packages" ;;
        pacman)  echo "sudo pacman -S --noconfirm $packages" ;;
        zypper)  echo "sudo zypper install -y $packages" ;;
        apk)     echo "sudo apk add $packages" ;;
        brew)    echo "brew install $packages" ;;
    esac
}

# Runs the package install with an explicit argument array (no eval).
run_package_install() {
    local manager="$1"
    shift
    case "$manager" in
        apt-get) sudo apt-get install -y "$@" ;;
        dnf)     sudo dnf install -y "$@" ;;
        yum)     sudo yum install -y "$@" ;;
        pacman)  sudo pacman -S --noconfirm "$@" ;;
        zypper)  sudo zypper install -y "$@" ;;
        apk)     sudo apk add "$@" ;;
        brew)    brew install "$@" ;;
        *)       return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

python_meets_minimum() {
    "$1" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, $MIN_PYTHON_MINOR) else 1)" 2>/dev/null
}

find_python() {
    local candidate
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && python_meets_minimum "$candidate"; then
            PYTHON_CMD="$candidate"
            return 0
        fi
    done
    return 1
}

require_python() {
    if find_python; then
        say_ok "Python $("$PYTHON_CMD" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])') detected"
        return 0
    fi

    say_err "Python 3.$MIN_PYTHON_MINOR or newer is required but was not found."
    local manager
    manager="$(detect_package_manager)"
    echo ""
    echo "  Install Python, then re-run this script:"
    echo ""
    if [[ -n "$manager" ]]; then
        echo "      $(install_command_for "$manager" "$(python_package_for "$manager")")"
    else
        echo "      https://www.python.org/downloads/"
    fi
    echo ""
    exit 1
}

# ---------------------------------------------------------------------------
# pipx
# ---------------------------------------------------------------------------

resolve_pipx() {
    if command -v pipx >/dev/null 2>&1; then
        PIPX_CMD="pipx"
        return 0
    fi
    if "$PYTHON_CMD" -m pipx --version >/dev/null 2>&1; then
        PIPX_CMD="$PYTHON_CMD -m pipx"
        return 0
    fi
    return 1
}

# Try the distro package manager first (the only route that works on
# externally-managed systems), then fall back to `pip install --user pipx`
# for older distros where system pip is still writable.
ensure_pipx() {
    if resolve_pipx; then
        say_ok "pipx available"
        return 0
    fi

    say_info "pipx is not installed. It is the recommended way to install CLI tools."

    local manager package
    manager="$(detect_package_manager)"
    if [[ -n "$manager" ]]; then
        package="$(pipx_package_for "$manager")"
        echo "  RadSim can install pipx with:"
        echo "      $(install_command_for "$manager" "$package")"
        if confirm "Run this now?"; then
            if run_package_install "$manager" $package && resolve_pipx; then
                say_ok "pipx installed"
                return 0
            fi
            say_warn "Package install did not provide pipx; trying pip --user."
        fi
    fi

    if "$PYTHON_CMD" -m pip install --user pipx >/dev/null 2>&1 && resolve_pipx; then
        say_ok "pipx installed via pip --user"
        return 0
    fi

    return 1
}

print_pipx_help() {
    local manager
    manager="$(detect_package_manager)"
    say_err "Could not set up pipx automatically."
    echo ""
    echo "  Modern Linux blocks 'pip install' into the system Python (PEP 668)."
    echo "  Install pipx, then RadSim, by running:"
    echo ""
    if [[ -n "$manager" ]]; then
        echo "      $(install_command_for "$manager" "$(pipx_package_for "$manager")")"
    else
        echo "      $PYTHON_CMD -m pip install --user pipx"
    fi
    echo "      pipx ensurepath"
    echo "      pipx install $PACKAGE_NAME"
    echo ""
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

install_radsim() {
    say_info "Installing RadSim with pipx..."

    # $PIPX_CMD may be "pipx" or "python3 -m pipx"; word-splitting is intended.
    # shellcheck disable=SC2086
    if $PIPX_CMD install "$PACKAGE_NAME"; then
        # shellcheck disable=SC2086
        $PIPX_CMD ensurepath >/dev/null 2>&1 || true
        say_ok "RadSim installed"
        return 0
    fi

    say_warn "pipx reports RadSim may already be installed; upgrading instead."
    # shellcheck disable=SC2086
    if $PIPX_CMD upgrade "$PACKAGE_NAME"; then
        say_ok "RadSim upgraded"
        return 0
    fi

    return 1
}

handle_existing_config() {
    local config_dir="$HOME/.radsim"
    [[ -d "$config_dir" ]] || return 0

    say_warn "Existing RadSim config found at ~/.radsim/ (API keys and settings)."
    if confirm "Remove it for a fresh setup? Default keeps it"; then
        rm -rf "$config_dir"
        say_ok "Old configuration removed. Setup will run on first launch."
    else
        say_ok "Keeping existing configuration."
    fi
}

verify_and_report() {
    echo ""
    echo "================================================"
    echo "  RadSim installed successfully!"
    echo "================================================"
    echo ""

    if command -v radsim >/dev/null 2>&1; then
        say_ok "'radsim' command is available"
        echo ""
        echo "  Run RadSim:"
        echo "     radsim"
    else
        echo "  Almost done — 'radsim' is not on your PATH in this shell yet."
        echo ""
        echo "  Restart your terminal (or open a new one), then run:"
        echo "     radsim"
    fi

    echo ""
    echo "  On first run, RadSim guides you through setup"
    echo "  (provider selection, API key, preferences)."
    echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    print_banner
    say_ok "Platform: $(distro_name) ($(uname -m))"

    require_python

    if ! ensure_pipx; then
        print_pipx_help
        exit 1
    fi

    handle_existing_config

    if ! install_radsim; then
        say_err "Installation failed."
        print_pipx_help
        exit 1
    fi

    verify_and_report
}

main "$@"
