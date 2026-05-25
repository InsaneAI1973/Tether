#!/usr/bin/env bash
# Tether — KDE/CachyOS Edition — Installer
# Target: CachyOS (Arch-based), KDE Plasma on Wayland
set -euo pipefail

INSTALL_DIR=/opt/tether-kde
SERVICE_DIR="${HOME}/.config/systemd/user"
DOLPHIN_DIR="${HOME}/.local/share/kservices5/ServiceMenus"
AUTOSTART_DIR="${HOME}/.config/autostart"
APPS_DIR="${HOME}/.local/share/applications"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── colour output ─────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    G='\033[0;32m' Y='\033[1;33m' C='\033[0;36m'
    R='\033[0;31m' B='\033[1m'    E='\033[0m'
else
    G='' Y='' C='' R='' B='' E=''
fi
info()    { echo -e "${G}[INFO]${E}  $*"; }
warn()    { echo -e "${Y}[WARN]${E}  $*"; }
error()   { echo -e "${R}[ERROR]${E} $*" >&2; }
section() { echo -e "\n${B}=== $* ===${E}"; }
die()     { error "$*"; exit 1; }

# ── pre-flight checks ─────────────────────────────────────────────────────────
section "Pre-flight checks"

# Must be on Arch/CachyOS
command -v pacman &>/dev/null || die "pacman not found. This installer is for Arch/CachyOS only."

# Must be on KDE Plasma
DE="${XDG_CURRENT_DESKTOP:-}${DESKTOP_SESSION:-}"
echo "$DE" | grep -qi 'kde\|plasma' || \
    warn "KDE/Plasma not detected in XDG_CURRENT_DESKTOP. Continuing anyway — ensure you are running KDE."

# Wayland check — informational only
if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
    info "Wayland session detected. ✓"
elif [[ -n "${DISPLAY:-}" ]]; then
    warn "X11 session detected. Tether works on X11 but is designed for Wayland."
else
    warn "No display session detected. Installing in headless mode — CLI only."
fi

# Must not run as root
[[ "${EUID}" -ne 0 ]] || die "Do not run this installer as root. It will call sudo as needed."

# ── dependencies ──────────────────────────────────────────────────────────────
section "Installing dependencies (pacman)"

PKGS=(
    python                  # Python 3 interpreter
    python-pyqt5            # Qt5 GUI framework
    python-dbus             # D-Bus Python bindings
    python-gobject          # GLib/GObject bindings (D-Bus main loop)
    kwallet                 # KDE credential store
    kwalletmanager          # KWallet GUI (allows user to manage stored passwords)
    polkit                  # Privilege escalation framework
    polkit-kde-agent        # KDE polkit agent — shows password dialog on Wayland
    rsync                   # Transfer engine with resume and progress
    cifs-utils              # SMB/CIFS mount support
    nfs-utils               # NFS mount support
    sshfs                   # SSHFS mount support
    findutils               # findmnt (part of util-linux, but ensure present)
)

info "Running: pacman -Syu --needed ${PKGS[*]}"
sudo pacman -Syu --needed --noconfirm "${PKGS[@]}" || \
    die "Package install failed. Check your internet connection and pacman mirrors."

info "Dependencies installed. ✓"

# ── install files ─────────────────────────────────────────────────────────────
section "Installing Tether to ${INSTALL_DIR}"

sudo mkdir -p "${INSTALL_DIR}"
for f in daemon.py client.py credentials.py frontend.py cli.py launcher.py; do
    sudo cp "${SCRIPT_DIR}/${f}" "${INSTALL_DIR}/"
done

# Copy and make executable: update script and uninstall script
for f in update.sh uninstall.sh; do
    if [[ -f "${SCRIPT_DIR}/${f}" ]]; then
        sudo cp "${SCRIPT_DIR}/${f}" "${INSTALL_DIR}/${f}"
        sudo chmod +x "${INSTALL_DIR}/${f}"
    fi
done

# Permissions:
#   .py source files  → 644 root:root  (readable, not world-executable)
#   entry points      → 755 root:root
sudo find "${INSTALL_DIR}" -name '*.py' -exec chmod 644 {} \;
sudo chmod 755 "${INSTALL_DIR}/launcher.py"
sudo chown -R root:root "${INSTALL_DIR}"

# Launcher symlink — remove first to handle re-install cleanly
sudo rm -f /usr/local/bin/tether
sudo ln -s "${INSTALL_DIR}/launcher.py" /usr/local/bin/tether
info "Launcher: /usr/local/bin/tether ✓"

# ── systemd user service ──────────────────────────────────────────────────────
section "Installing systemd user service"

mkdir -p "${SERVICE_DIR}"
sed "s|/opt/tether-kde|${INSTALL_DIR}|g" \
    "${SCRIPT_DIR}/tether-daemon.service" \
    > "${SERVICE_DIR}/tether-daemon.service"

systemctl --user daemon-reload

if systemctl --user enable --now tether-daemon.service 2>/dev/null; then
    info "Daemon service enabled and started. ✓"
else
    warn "Could not start daemon service automatically.
      Start manually: systemctl --user start tether-daemon.service
      Check logs:     journalctl --user -u tether-daemon.service"
fi

# ── Dolphin service menu ──────────────────────────────────────────────────────
section "Installing Dolphin service menu"

mkdir -p "${DOLPHIN_DIR}"
cp "${SCRIPT_DIR}/tether-dolphin.desktop" "${DOLPHIN_DIR}/"

# Rebuild KDE service menu cache
if command -v kbuildsycoca6 &>/dev/null; then
    kbuildsycoca6 --noincremental 2>/dev/null && info "KDE service cache rebuilt (kbuildsycoca6). ✓" || true
elif command -v kbuildsycoca5 &>/dev/null; then
    kbuildsycoca5 --noincremental 2>/dev/null && info "KDE service cache rebuilt (kbuildsycoca5). ✓" || true
fi

# ── Application .desktop file ─────────────────────────────────────────────────
section "Installing application entry"

mkdir -p "${APPS_DIR}"
cp "${SCRIPT_DIR}/tether.desktop" "${APPS_DIR}/"
update-desktop-database "${APPS_DIR}" 2>/dev/null || true
info "Application entry installed. ✓"

# ── KDE autostart ─────────────────────────────────────────────────────────────
section "Configuring KDE autostart"

mkdir -p "${AUTOSTART_DIR}"
# Autostart launches the tray applet when Plasma starts
cat > "${AUTOSTART_DIR}/tether.desktop" << 'DESKTOP'
[Desktop Entry]
Name=Tether
Exec=/usr/local/bin/tether
Icon=network-server
Type=Application
X-KDE-autostart-condition=tether/General/Autostart/true
X-KDE-StartupNotify=false
DESKTOP
info "KDE autostart entry created. ✓"

# ── Data directories ──────────────────────────────────────────────────────────
section "Creating data directories"

DATA_DIR="${HOME}/.local/share/tether"
CRED_DIR="${DATA_DIR}/credentials"

mkdir -p "${DATA_DIR}"
mkdir -p "${CRED_DIR}"
chmod 700 "${DATA_DIR}"
chmod 700 "${CRED_DIR}"
info "Data directory: ${DATA_DIR} (chmod 700) ✓"

# Samba credentials directory (only if cifs-utils installed successfully)
if command -v mount.cifs &>/dev/null; then
    sudo mkdir -p /etc/samba
    sudo chmod 755 /etc/samba
    info "Samba directory: /etc/samba ✓"
fi

# ── Polkit check ──────────────────────────────────────────────────────────────
section "Polkit agent check"

if pgrep -x polkit-kde-authentic &>/dev/null || \
   pgrep -x "polkit-kde-authentication-agent-1" &>/dev/null; then
    info "KDE polkit agent is running. ✓"
else
    warn "KDE polkit agent does not appear to be running.
      pkexec password dialogs may not appear.
      It should start automatically with your Plasma session.
      If mount operations hang, check: systemctl --user status plasma-polkit-agent"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
section "Installation complete"

echo -e "
${B}Tether (KDE/CachyOS Edition) is installed.${E}

  ${B}Tray applet${E}
    The Tether icon will appear in your system tray.
    If not, run: ${C}tether${E}
    Or log out and back in (autostart is configured).

  ${B}Dolphin integration${E}
    Right-click any folder → Actions → Mount Network Location here…

  ${B}CLI${E}
    ${C}tether list${E}                     — show configured mounts
    ${C}tether add${E}                      — interactive add wizard
    ${C}tether watch${E}                    — live dashboard
    ${C}tether transfer <src> <dst>${E}     — rsync with progress + resume

  ${B}First run test${E}
    ${C}tether list${E}          (should print 'No mounts configured')
    ${C}tether watch${E}         (should show live dashboard)

  ${B}Logs${E}
    ${HOME}/.local/share/tether/tether.log
    journalctl --user -u tether-daemon.service -f

  ${B}Uninstall${E}
    ${Y}./uninstall.sh${E}
"
