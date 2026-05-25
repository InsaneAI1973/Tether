#!/usr/bin/env bash
# Tether — KDE/CachyOS Edition — Uninstaller
set -euo pipefail

echo "Removing Tether (KDE/CachyOS Edition)…"

# Stop and disable daemon
systemctl --user stop    tether-daemon.service 2>/dev/null || true
systemctl --user disable tether-daemon.service 2>/dev/null || true
rm -f "${HOME}/.config/systemd/user/tether-daemon.service"
systemctl --user daemon-reload 2>/dev/null || true

# Remove installed files
sudo rm -rf /opt/tether-kde
sudo rm -f  /usr/local/bin/tether

# Remove desktop integrations
rm -f "${HOME}/.local/share/kservices5/ServiceMenus/tether-dolphin.desktop"
rm -f "${HOME}/.local/share/applications/tether.desktop"
rm -f "${HOME}/.config/autostart/tether.desktop"

# Rebuild KDE cache
command -v kbuildsycoca6 &>/dev/null && kbuildsycoca6 --noincremental 2>/dev/null || true
command -v kbuildsycoca5 &>/dev/null && kbuildsycoca5 --noincremental 2>/dev/null || true

echo ""
echo "Tether removed."
echo ""
echo "Personal data preserved at: ${HOME}/.local/share/tether/"
echo "To fully remove:  rm -rf ${HOME}/.local/share/tether/"
echo ""
echo "KWallet credentials remain stored under the 'tether-mounts' folder."
echo "Remove them via KWallet Manager if desired."
