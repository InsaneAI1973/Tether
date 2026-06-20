#!/usr/bin/env bash
# Tether — KDE/CachyOS Edition — Uninstaller
set -euo pipefail

echo "Removing Tether (KDE/CachyOS Edition)…"

# ── Check for active Tether fstab entries ────────────────────────────────────
TETHER_FSTAB_LINES=$(grep -c '# tether:' /etc/fstab 2>/dev/null || true)
TETHER_FSTAB_LINES=${TETHER_FSTAB_LINES:-0}

if [[ "${TETHER_FSTAB_LINES}" -gt 0 ]]; then
    echo ""
    echo "Found ${TETHER_FSTAB_LINES} Tether-managed entry/entries in /etc/fstab:"
    grep '# tether:' /etc/fstab | sed 's/^/  /'
    echo ""
    read -r -p "Unmount these shares and remove their fstab entries now? [y/N] " REPLY
    if [[ "${REPLY,,}" == "y" ]]; then
        # Unmount each tether-managed mountpoint (best-effort, ignore failures)
        while IFS= read -r line; do
            mountpoint=$(echo "$line" | awk '{print $2}')
            if [[ -n "${mountpoint}" ]]; then
                echo "  Unmounting ${mountpoint}…"
                sudo umount -- "${mountpoint}" 2>/dev/null || true
            fi
        done < <(grep '# tether:' /etc/fstab)

        # Remove the fstab lines
        sudo cp /etc/fstab /etc/fstab.tether-uninstall.bak
        sudo sed -i '/# tether:/d' /etc/fstab
        echo "  fstab entries removed. Backup saved to /etc/fstab.tether-uninstall.bak"

        # Remove samba credential files
        sudo rm -f /etc/samba/.tether_* 2>/dev/null || true
        echo "  Samba credential files removed."
    else
        echo "  Leaving fstab entries and credential files in place."
        echo "  Shares will still mount on boot via fstab even without Tether installed."
    fi
fi

# ── Stop and disable daemon ───────────────────────────────────────────────────
systemctl --user stop    tether-daemon.service 2>/dev/null || true
systemctl --user disable tether-daemon.service 2>/dev/null || true
rm -f "${HOME}/.config/systemd/user/tether-daemon.service"
systemctl --user daemon-reload 2>/dev/null || true

# ── Remove installed files ────────────────────────────────────────────────────
sudo rm -rf /opt/tether-kde
sudo rm -f  /usr/local/bin/tether

# ── Remove desktop integrations ───────────────────────────────────────────────
rm -f "${HOME}/.local/share/kservices5/ServiceMenus/tether-dolphin.desktop"
rm -f "${HOME}/.local/share/applications/tether.desktop"
rm -f "${HOME}/.config/autostart/tether.desktop"

# ── Remove man page ────────────────────────────────────────────────────────────
sudo rm -f /usr/local/share/man/man1/tether.1
sudo mandb -q 2>/dev/null || true

# ── Rebuild KDE cache ──────────────────────────────────────────────────────────
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
