#!/usr/bin/env bash
# Setup script for server-inspector
# Installs server-inspector and its system dependencies on any Linux distro

set -euo pipefail

# ---------------------------------------------------------------------------
# Colors & logging
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# ---------------------------------------------------------------------------
# Package manager detection
# ---------------------------------------------------------------------------
_PKG_MANAGER=""
_apt_updated=0

detect_pkg_manager() {
    if [[ -n "$_PKG_MANAGER" ]]; then
        return 0
    fi
    if command -v apt-get &>/dev/null; then
        _PKG_MANAGER="apt"
    elif command -v pacman &>/dev/null; then
        _PKG_MANAGER="pacman"
    elif command -v dnf &>/dev/null; then
        _PKG_MANAGER="dnf"
    elif command -v zypper &>/dev/null; then
        _PKG_MANAGER="zypper"
    elif command -v apk &>/dev/null; then
        _PKG_MANAGER="apk"
    else
        _PKG_MANAGER="unknown"
    fi
}

# ---------------------------------------------------------------------------
# Privilege escalation helper
# ---------------------------------------------------------------------------
_run_privileged() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
    elif command -v sudo &>/dev/null; then
        sudo "$@"
    elif command -v doas &>/dev/null; then
        doas "$@"
    else
        log_error "Need root privileges but neither sudo nor doas is available"
        log_error "Run this script as root or install sudo/doas"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Multi-distro package installer
# ---------------------------------------------------------------------------
install_pkg() {
    detect_pkg_manager
    log_info "Installing package(s): $*"
    case "$_PKG_MANAGER" in
        apt)
            if [[ "$_apt_updated" -eq 0 ]]; then
                _run_privileged apt-get update -qq 2>/dev/null || log_warn "apt-get update had issues, continuing..."
                _apt_updated=1
            fi
            _run_privileged apt-get install -y -qq "$@" 2>&1 | grep -v "^W:" || true
            ;;
        pacman)
            _run_privileged pacman -Sy --noconfirm --needed "$@"
            ;;
        dnf)
            _run_privileged dnf install -y "$@"
            ;;
        zypper)
            _run_privileged zypper install -y "$@"
            ;;
        apk)
            _run_privileged apk add "$@"
            ;;
        *)
            log_error "No supported package manager found (apt/pacman/dnf/zypper/apk)"
            log_error "Please install manually: $*"
            return 1
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Download helper (curl-then-wget fallback)
# ---------------------------------------------------------------------------
download() {
    if command -v curl &>/dev/null; then
        curl -LsSf "$1"
    elif command -v wget &>/dev/null; then
        wget -qO- "$1"
    else
        log_error "Neither curl nor wget available"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Network checks
# ---------------------------------------------------------------------------
check_network() {
    log_info "Checking network connectivity..."
    if ! ping -c 1 -W 5 1.1.1.1 &>/dev/null; then
        log_error "No network connectivity"
        echo "  Please configure networking first:"
        echo "    1. Check cable / Wi-Fi connection"
        echo "    2. Get DHCP lease: sudo dhclient -v  (or: nmcli device connect <iface>)"
        echo "    3. Or set static IP: sudo ip addr add 192.168.1.100/24 dev eth0"
        return 1
    fi
    log_info "Network OK"

    log_info "Checking DNS..."
    if ! ping -c 1 -W 5 github.com &>/dev/null; then
        log_warn "DNS not working, attempting auto-fix..."
        if _run_privileged sh -c 'printf "nameserver 1.1.1.1\nnameserver 8.8.8.8\n" > /etc/resolv.conf'; then
            sleep 1
            if ! ping -c 1 -W 5 github.com &>/dev/null; then
                log_error "Cannot resolve github.com even after DNS fix"
                return 1
            fi
            log_info "DNS fixed"
        else
            log_warn "Could not auto-fix DNS (no root access)"
            log_warn "Manually run: echo 'nameserver 1.1.1.1' | sudo tee /etc/resolv.conf"
            return 1
        fi
    fi
    log_info "DNS OK"
}

# ---------------------------------------------------------------------------
# Prerequisites: curl/wget, unzip, jq
# ---------------------------------------------------------------------------
ensure_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
        install_pkg curl || install_pkg wget
    fi
    if ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
        log_error "Could not install curl or wget"
        return 1
    fi

    if ! command -v unzip &>/dev/null; then
        install_pkg unzip
    fi
    if ! command -v unzip &>/dev/null; then
        log_error "Could not install unzip"
        return 1
    fi

    if ! command -v jq &>/dev/null; then
        install_pkg jq
    fi
    if ! command -v jq &>/dev/null; then
        log_error "Could not install jq"
        return 1
    fi

    log_info "Prerequisites OK"
}

# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------
ensure_git() {
    if command -v git &>/dev/null; then
        return 0
    fi
    install_pkg git
    if ! command -v git &>/dev/null; then
        log_error "Could not install git"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# uv (Python package/tool manager)
# ---------------------------------------------------------------------------
ensure_uv() {
    if command -v uv &>/dev/null; then
        log_info "uv already installed: $(command -v uv)"
        return 0
    fi

    log_info "Installing uv..."
    download https://astral.sh/uv/install.sh | sh

    # Ensure ~/.local/bin is in PATH for this session
    local uv_dir="$HOME/.local/bin"
    if [[ ":$PATH:" != *":$uv_dir:"* ]]; then
        export PATH="$uv_dir:$PATH"
    fi

    if ! command -v uv &>/dev/null; then
        log_error "Could not install uv"
        return 1
    fi
    log_info "uv installed: $(command -v uv)"
}

# ---------------------------------------------------------------------------
# Install a Python tool from a GitHub repo via uv
# Tries SSH first (with auto-discovered key), falls back to HTTPS.
# Usage: install_from_github <org>/<repo> [extra_dep_repo1] [extra_dep_repo2] ...
# Extra dep repos are passed as --with arguments
# ---------------------------------------------------------------------------
install_from_github() {
    local repo="$1"
    shift
    local extra_dep_repos=("$@")

    # Find an SSH key: check current user, then SUDO_USER's home
    local ssh_key=""
    local search_dirs=("$HOME/.ssh")
    if [[ -n "${SUDO_USER:-}" ]]; then
        local sudo_home
        sudo_home=$(getent passwd "$SUDO_USER" 2>/dev/null | cut -d: -f6 || echo "")
        [[ -n "$sudo_home" ]] && search_dirs=("$sudo_home/.ssh" "${search_dirs[@]}")
    fi

    for dir in "${search_dirs[@]}"; do
        for key in "$dir/id_ed25519" "$dir/id_rsa" "$dir/id_ecdsa"; do
            if [[ -f "$key" ]]; then
                ssh_key="$key"
                break 2
            fi
        done
    done

    # Build --with arguments for extra dependencies
    local ssh_with_args=()
    local https_with_args=()
    for dep_repo in "${extra_dep_repos[@]}"; do
        local dep_name
        dep_name=$(basename "$dep_repo")
        ssh_with_args+=(--with "$dep_name @ git+ssh://git@github.com/$dep_repo")
        https_with_args+=(--with "$dep_name @ git+https://github.com/$dep_repo")
    done

    # Try SSH (private repos with SSH key)
    if [[ -n "$ssh_key" ]]; then
        log_info "Using SSH key: $ssh_key"
        if GIT_SSH_COMMAND="ssh -i $ssh_key -o StrictHostKeyChecking=accept-new" \
            uv tool install --no-sources "${ssh_with_args[@]}" "git+ssh://git@github.com/$repo" 2>&1; then
            return 0
        fi
        log_warn "SSH install failed, trying HTTPS..."
    fi

    # Fall back to HTTPS (public repos, or repos with git credential helpers)
    uv tool install --no-sources "${https_with_args[@]}" "git+https://github.com/$repo"
}

# ===========================================================================
# Main
# ===========================================================================
PYTHON_VERSION="3.14"

main() {
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║          Server Inspector - Setup Script                  ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo

    # Bootstrap: network, prerequisites, git, uv
    check_network
    ensure_prerequisites
    ensure_git
    ensure_uv

    # Install Python via uv
    log_info "Installing Python $PYTHON_VERSION via uv..."
    uv python install "$PYTHON_VERSION"
    log_info "Python $PYTHON_VERSION installed"

    # Install server-inspector from GitHub
    log_info "Installing server-inspector from GitHub..."
    install_from_github casaeureka/psw-server-inspector || {
        log_error "Failed to install server-inspector"
        exit 1
    }

    # Hard verify: the binary must exist after install
    if ! command -v server-inspector &>/dev/null; then
        log_error "uv tool install reported success but 'server-inspector' binary not found in PATH"
        log_error "Checked: \$HOME/.local/bin/server-inspector = $HOME/.local/bin/server-inspector"
        ls -la "$HOME/.local/bin/server-inspector" 2>/dev/null || log_error "  -> does not exist"
        log_error "uv tool list:"
        uv tool list 2>&1 | grep -i server-inspector || log_error "  -> not in uv tool list"
        exit 1
    fi
    log_info "server-inspector installed: $(command -v server-inspector)"

    # System dependencies
    # server-inspector uses: lspci, ethtool, dmidecode, smartctl, nvme, ipmitool, lsusb, lscpu, lsblk, etc.
    log_info "Installing server-inspector system dependencies..."
    install_pkg pciutils        # lspci (GPU, NIC, USB controller detection)
    install_pkg usbutils        # lsusb (USB serial device detection: Zigbee, Z-Wave dongles)
    install_pkg ethtool         # network interface speed detection
    install_pkg dmidecode       # motherboard, memory, BIOS info
    install_pkg smartmontools   # smartctl (storage health)
    install_pkg nvme-cli        # nvme (NVMe drive info)
    install_pkg ipmitool        # IPMI/BMC management interface

    # Create symlink so it works without PATH changes
    local bin_path
    bin_path="$(command -v server-inspector)"
    if [[ ! -f "$bin_path" ]]; then
        log_error "Cannot find server-inspector binary to create symlink"
        exit 1
    fi
    _run_privileged ln -sf "$bin_path" /usr/local/bin/server-inspector

    # Final verification: the symlink must resolve to a real binary
    if ! /usr/local/bin/server-inspector --version &>/dev/null; then
        log_error "Symlink created but /usr/local/bin/server-inspector doesn't work"
        ls -la /usr/local/bin/server-inspector 2>&1 | sed 's/^/  /'
        exit 1
    fi

    echo
    log_info "Setup complete!"
    echo
    echo "  Installed: $(command -v server-inspector) -> $(/usr/local/bin/server-inspector --version 2>&1 || echo 'unknown version')"
    echo
    echo "  Usage:"
    echo "    server-inspector <name>  → generates server-specs-<name>.json + hardware-<name>.yml"
    echo
    echo "  Example:"
    echo "    server-inspector aio"
    echo
}

main "$@"
