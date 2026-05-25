#!/usr/bin/env bash
# Tether Update Script
# Copies new files to /opt/tether-kde and restarts services safely.
#
# Usage:
#   bash update.sh                    # run from folder containing new files
#   bash update.sh /path/to/new/files # specify source folder explicitly
#
set -euo pipefail

INSTALL_DIR=/opt/tether-kde

# Source directory: first argument if given, otherwise current directory
if [[ -n "${1:-}" ]]; then
    SCRIPT_DIR="$(cd "$1" && pwd)"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # If running from install dir, require explicit source path
    if [[ "${SCRIPT_DIR}" == "${INSTALL_DIR}" ]]; then
        echo "ERROR: update.sh is being run from the install directory."
        echo ""
        echo "Please run it from the folder containing the new files:"
        echo "  cd ~/Downloads/kde-cachy"
        echo "  bash /opt/tether-kde/update.sh"
        echo ""
        echo "Or pass the source folder as an argument:"
        echo "  bash /opt/tether-kde/update.sh ~/Downloads/kde-cachy"
        exit 1
    fi
fi

if [[ -t 1 ]]; then
    G='\033[0;32m' Y='\033[1;33m' R='\033[0;31m' B='\033[1m' E='\033[0m'
else
    G='' Y='' R='' B='' E=''
fi

info()  { echo -e "${G}[INFO]${E}  $*"; }
warn()  { echo -e "${Y}[WARN]${E}  $*"; }
error() { echo -e "${R}[ERROR]${E} $*" >&2; }

echo -e "\n${B}=== Tether Update ===${E}\n"

# Step 1 — Stop the tray applet if running
info "Stopping Tether tray applet…"
pkill -f "tether-kde/launcher.py" 2>/dev/null || true
pkill -f "tether-kde/frontend.py" 2>/dev/null || true
sleep 1

# Step 2 — Stop the daemon cleanly
info "Stopping Tether daemon…"
systemctl --user stop tether-daemon.service 2>/dev/null || true
# Force-kill any lingering daemon process
pkill -f "tether-kde/daemon.py" 2>/dev/null || true
sleep 2

# Step 3 — Copy new files
info "Installing new files to ${INSTALL_DIR}…"
for f in daemon.py client.py frontend.py launcher.py credentials.py cli.py; do
    if [[ -f "${SCRIPT_DIR}/${f}" ]]; then
        sudo cp "${SCRIPT_DIR}/${f}" "${INSTALL_DIR}/${f}"
        info "  Updated: ${f}"
    fi
done

# Copy service file if present
if [[ -f "${SCRIPT_DIR}/tether-daemon.service" ]]; then
    cp "${SCRIPT_DIR}/tether-daemon.service" \
       "${HOME}/.config/systemd/user/tether-daemon.service"
    systemctl --user daemon-reload
    info "  Updated: tether-daemon.service"
fi

# Step 4 — Restart daemon
info "Starting Tether daemon…"
systemctl --user start tether-daemon.service
sleep 2

if systemctl --user is-active tether-daemon.service &>/dev/null; then
    info "Daemon running. ✓"
else
    error "Daemon failed to start."
    echo "Check: journalctl --user -u tether-daemon.service -n 30"
    exit 1
fi

# Step 5 — Relaunch tray applet
info "Launching Tether…"
nohup python3 "${INSTALL_DIR}/launcher.py" &>/dev/null &
sleep 1

echo -e "\n${G}Update complete. Tether ${B}$(grep -o \"VERSION = '[^']*'\" ${INSTALL_DIR}/frontend.py | head -1 | cut -d\' -f2)${E}${G} is running.${E}\n"
