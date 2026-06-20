#!/usr/bin/env bash
# Tether Release Packager
# Creates a self-contained release tarball ready for GitHub release upload.
# Run this from the kde-cachy directory or from the repo root.
#
# Usage:
#   bash kde-cachy/make-release.sh
#
set -euo pipefail

# ── Locate script and repo root ───────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${SCRIPT_DIR}")"

# ── Read version from daemon.py ───────────────────────────────────────────────
VERSION=$(python3 -c "
import re, sys
src = open('${SCRIPT_DIR}/daemon.py').read()
m = re.search(r\"VERSION = '([^']+)'\", src)
print(m.group(1) if m else sys.exit(1))
")

RELEASE_NAME="tether-v${VERSION}-kde-cachy"
OUTPUT_DIR="${REPO_ROOT}/release"
TARBALL="${OUTPUT_DIR}/${RELEASE_NAME}.tar.gz"

# ── Colors ────────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    G='\033[0;32m' Y='\033[1;33m' B='\033[1m' E='\033[0m'
else
    G='' Y='' B='' E=''
fi
info() { echo -e "${G}[INFO]${E}  $*"; }
warn() { echo -e "${Y}[WARN]${E}  $*"; }

echo -e "\n${B}=== Tether Release Packager ===${E}"
echo -e "Version : ${B}${VERSION}${E}"
echo -e "Output  : ${B}${TARBALL}${E}\n"

# ── Staging area ──────────────────────────────────────────────────────────────
STAGE=$(mktemp -d)
PKG="${STAGE}/${RELEASE_NAME}"
mkdir -p "${PKG}"

# ── Python source files ───────────────────────────────────────────────────────
info "Copying Python source files..."
for f in daemon.py client.py frontend.py launcher.py cli.py credentials.py; do
    if [[ -f "${SCRIPT_DIR}/${f}" ]]; then
        cp "${SCRIPT_DIR}/${f}" "${PKG}/"
        info "  + ${f}"
    else
        warn "  MISSING: ${f}"
    fi
done

# ── Shell scripts (ensure executable) ────────────────────────────────────────
info "Copying scripts..."
for f in install.sh update.sh uninstall.sh; do
    if [[ -f "${SCRIPT_DIR}/${f}" ]]; then
        cp "${SCRIPT_DIR}/${f}" "${PKG}/"
        chmod +x "${PKG}/${f}"
        info "  + ${f}  (executable)"
    else
        warn "  MISSING: ${f}"
    fi
done

# ── System files ─────────────────────────────────────────────────────────────
info "Copying system files..."
for f in tether-daemon.service tether.1; do
    if [[ -f "${SCRIPT_DIR}/${f}" ]]; then
        cp "${SCRIPT_DIR}/${f}" "${PKG}/"
        info "  + ${f}"
    else
        warn "  MISSING: ${f}"
    fi
done

# ── Repo root files ───────────────────────────────────────────────────────────
info "Copying repo files..."
for f in README.md CHANGELOG.md LICENSE; do
    if [[ -f "${REPO_ROOT}/${f}" ]]; then
        cp "${REPO_ROOT}/${f}" "${PKG}/"
        info "  + ${f}"
    else
        warn "  MISSING: ${f}  (looked in ${REPO_ROOT})"
    fi
done

# ── INSTALL quickstart file ───────────────────────────────────────────────────
cat > "${PKG}/INSTALL" << 'INSTALLEOF'
Tether — Network Mount Manager for KDE Plasma
==============================================

QUICK INSTALL
-------------
  chmod +x install.sh
  ./install.sh

REQUIREMENTS
------------
  CachyOS or Arch Linux with KDE Plasma (Wayland or X11)

WHAT THE INSTALLER DOES
-----------------------
  1. Installs all dependencies via pacman (official repos only — no AUR)
  2. Copies Tether to /opt/tether-kde/
  3. Creates launcher at /usr/local/bin/tether
  4. Installs and starts the background daemon service
  5. Adds Tether to KDE autostart on login
  6. Installs Dolphin file manager integration
  7. Installs man page  (try: man tether)

FIRST RUN
---------
  tether            — launch the GUI
  tether list       — list mounted shares
  tether watch      — live status dashboard

UPDATING
--------
  Download the new release tarball, extract it, then run:
    bash update.sh

UNINSTALLING
------------
  bash /opt/tether-kde/uninstall.sh

MORE INFO
---------
  https://github.com/InsaneAI1973/Tether
INSTALLEOF
info "  + INSTALL"

# ── Build tarball ─────────────────────────────────────────────────────────────
mkdir -p "${OUTPUT_DIR}"
tar -czf "${TARBALL}" -C "${STAGE}" "${RELEASE_NAME}"
rm -rf "${STAGE}"

# ── Summary ───────────────────────────────────────────────────────────────────
SIZE=$(du -sh "${TARBALL}" | cut -f1)
echo ""
info "Package created: ${B}${TARBALL}${E}  (${SIZE})"
echo ""
echo -e "${B}Contents:${E}"
tar -tzf "${TARBALL}" | sed 's|^|  |'
echo ""
echo -e "${G}Done!${E}"
echo ""
echo -e "${B}Next steps:${E}"
echo -e "  1. Upload ${B}${RELEASE_NAME}.tar.gz${E} to the GitHub release"
echo -e "  2. Update README installation section with this one-liner:"
echo ""
echo -e "     ${B}curl -L https://github.com/InsaneAI1973/Tether/releases/latest/download/${RELEASE_NAME}.tar.gz | tar -xz && cd ${RELEASE_NAME} && ./install.sh${E}"
echo ""
