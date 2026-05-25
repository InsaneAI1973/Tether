#!/usr/bin/env python3
"""
Tether — KDE/CachyOS Edition
KDE Plasma / Wayland Frontend
Version 0.5.0

Two modes:
  - Simple Wizard (default): guided step-by-step, no technical knowledge needed
  - Advanced Mode: direct form for power users

All optional settings accessible via GUI — no terminal required.
"""

import sys
import json
import logging
import subprocess
import threading

from PyQt5.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QAction,
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLineEdit, QComboBox, QPushButton, QLabel,
    QProgressBar, QWidget, QScrollArea, QMessageBox,
    QTabWidget, QFrame, QSizePolicy, QWizard, QWizardPage,
    QListWidget, QListWidgetItem, QCheckBox, QGroupBox,
    QStackedWidget, QRadioButton, QButtonGroup, QSplitter,
    QAbstractItemView,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QSettings
from PyQt5.QtGui import QIcon, QFont

log = logging.getLogger('tether.frontend')
VERSION = '0.7.1'

# Persistent settings
_settings = QSettings('Tether', 'Tether')


def _get_advanced_mode() -> bool:
    return _settings.value('advanced_mode', False, type=bool)


def _set_advanced_mode(val: bool):
    _settings.setValue('advanced_mode', val)


# ── Background poller ─────────────────────────────────────────────────────────

class DaemonPoller(QThread):
    mounts_ready    = pyqtSignal(dict)
    transfers_ready = pyqtSignal(dict)
    error_occurred  = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = True

    def run(self):
        try:
            from client import TetherClient
            client = TetherClient()
        except RuntimeError as e:
            self.error_occurred.emit(str(e))
            return
        while self._active:
            try:
                self.mounts_ready.emit(client.list_mounts())
                self.transfers_ready.emit(client.list_transfers())
            except Exception as e:
                log.warning('Poll error: %s', e)
            self.msleep(2000)

    def stop(self):
        self._active = False
        self.quit()
        self.wait(3000)


# ── Network discovery helpers ─────────────────────────────────────────────────

import shutil as _shutil
import os as _os


def _find_tool(name: str) -> str:
    """Resolve full path to a CLI tool, logging clearly if not found."""
    found = _shutil.which(name)
    if found:
        return found
    for candidate in (f'/usr/bin/{name}', f'/usr/sbin/{name}',
                      f'/bin/{name}', f'/sbin/{name}'):
        if _os.path.isfile(candidate) and _os.access(candidate, _os.X_OK):
            log.debug('Tool %s found at %s (fallback)', name, candidate)
            return candidate
    log.warning('Tool %r not found. PATH=%s', name, _os.environ.get('PATH','(empty)'))
    return name


def _tool_env() -> dict:
    """Return environment with an expanded PATH for subprocess calls."""
    env = dict(_os.environ)
    env['PATH'] = '/usr/bin:/usr/sbin:/bin:/sbin:' + env.get('PATH', '')
    return env


def _parse_shares(output: str) -> list:
    """
    Parse smbclient -L output into a list of Disk share names.

    Handles share names containing spaces (e.g. "Audio Books", "Blue Iris - Storage")
    by finding the position of the word 'Disk' in each line rather than splitting
    on whitespace. IPC$ and hidden ($) shares are excluded.

    Tested against TrueNAS output format.
    """
    shares   = []
    in_section = False

    for line in output.splitlines():
        stripped = line.strip()

        # Locate the header row — marks start of share table
        if 'Sharename' in stripped and 'Type' in stripped:
            in_section = True
            continue

        if not in_section:
            continue

        # Skip separator, empty lines, and trailing status messages
        if (not stripped
                or stripped.startswith('-')
                or stripped.startswith('SMB')
                or stripped.startswith('Server')
                or stripped.startswith('Workgroup')):
            continue

        # Extract share name by finding where ' Disk' appears in the line.
        # Everything before it (trimmed) is the share name — handles spaces.
        disk_pos = stripped.find(' Disk')
        if disk_pos > 0:
            name = stripped[:disk_pos].strip()
            # Skip IPC and hidden admin shares
            if name and not name.endswith('$'):
                shares.append(name)

    return shares


def discover_servers() -> list:
    """
    Return list of (name, ip) tuples visible on the local network.
    Uses nmblookup broadcast + avahi-browse for mDNS.
    Returns empty list gracefully if tools are unavailable.
    """
    servers = set()
    nmb   = _find_tool('nmblookup')
    avahi = _find_tool('avahi-browse')
    env   = _tool_env()

    try:
        r = subprocess.run(
            [nmb, '-S', '*'],
            capture_output=True, text=True, timeout=8, env=env
        )
        log.debug('nmblookup stdout: %s', r.stdout[:400])
        log.debug('nmblookup stderr: %s', r.stderr[:200])
        for line in r.stdout.splitlines():
            if '<00>' in line and 'querying' not in line.lower():
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[1].split('<')[0].strip()
                    ip   = parts[0].strip()
                    if name and not name.startswith('*'):
                        servers.add((name, ip))
    except FileNotFoundError:
        log.warning('nmblookup not found — install samba')
    except subprocess.TimeoutExpired:
        log.warning('nmblookup timed out')
    except Exception as e:
        log.warning('nmblookup error: %s', e)

    try:
        r = subprocess.run(
            [avahi, '-t', '-r', '-p', '_smb._tcp'],
            capture_output=True, text=True, timeout=6, env=env
        )
        log.debug('avahi-browse stdout: %s', r.stdout[:400])
        for line in r.stdout.splitlines():
            parts = line.split(';')
            # avahi -p format: =;interface;IPv4orIPv6;name;type;domain;host;ip;port;
            if len(parts) >= 8 and parts[0] == '=':
                proto = parts[2]   # 'IPv4' or 'IPv6'
                name  = parts[3]
                ip    = parts[7]
                # Skip IPv6 entries — avahi explicitly labels them
                if proto == 'IPv6':
                    log.debug('Skipping IPv6 discovery entry: %s %s', name, ip)
                    continue
                if name:
                    servers.add((name, ip))
    except FileNotFoundError:
        log.debug('avahi-browse not found — skipping mDNS')
    except subprocess.TimeoutExpired:
        log.debug('avahi-browse timed out')
    except Exception as e:
        log.debug('avahi-browse error: %s', e)

    log.info('Discovery found %d server(s): %s', len(servers), servers)

    # Only filter out IPv6 entries — keep ALL IPv4 entries even if same
    # server name appears multiple times (legitimate multiple interfaces)
    import socket as _socket
    result = []
    for name, ip in sorted(servers, key=lambda x: x[0].lower()):
        is_ipv6 = False
        try:
            _socket.inet_pton(_socket.AF_INET6, ip)
            is_ipv6 = True
        except OSError:
            pass
        if is_ipv6:
            log.debug('Skipping IPv6 entry: %s %s', name, ip)
            continue
        result.append((name, ip))

    log.info('After IPv6 filter: %s', result)
    return result


def list_shares(host: str) -> list:
    """List shares anonymously. Returns empty list if auth required."""
    smbclient = _find_tool('smbclient')
    env       = _tool_env()
    try:
        r = subprocess.run(
            [smbclient, '-L', host, '-N',
             '--option=client min protocol=SMB2'],
            capture_output=True, text=True, timeout=12, env=env
        )
        log.debug('smbclient anon stdout: %s', r.stdout[:400])
        log.debug('smbclient anon stderr: %s', r.stderr[:200])
        return _parse_shares(r.stdout)
    except FileNotFoundError:
        log.error('smbclient not found — install smbclient or cifs-utils')
        return []
    except subprocess.TimeoutExpired:
        log.warning('smbclient timed out for %s', host)
        return []
    except Exception as e:
        log.warning('smbclient anon failed for %s: %s', host, e)
        return []


def list_shares_auth(host: str, username: str, password: str) -> list:
    """List shares with credentials."""
    smbclient = _find_tool('smbclient')
    env       = _tool_env()
    try:
        r = subprocess.run(
            [smbclient, '-L', host,
             '-U', f'{username}%{password}',
             '--option=client min protocol=SMB2'],
            capture_output=True, text=True, timeout=12, env=env
        )
        log.debug('smbclient auth stdout: %s', r.stdout[:400])
        log.debug('smbclient auth stderr: %s', r.stderr[:200])
        return _parse_shares(r.stdout)
    except FileNotFoundError:
        log.error('smbclient not found — install smbclient or cifs-utils')
        return []
    except subprocess.TimeoutExpired:
        log.warning('smbclient auth timed out for %s', host)
        return []
    except Exception as e:
        log.warning('smbclient auth failed for %s: %s', host, e)
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# SIMPLE WIZARD
# ═══════════════════════════════════════════════════════════════════════════════

class WizardPageServer(QWizardPage):
    """Step 1 — Choose a server."""

    # Signal for thread-safe UI update from background scan thread
    _scan_complete = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle('Step 1 of 4 — Choose a Server')
        self.setSubTitle(
            'Tether will search your network for file servers. '
            'Select one from the list, or type an address manually.'
        )
        self._servers = []
        self._scan_complete.connect(self._on_scan_done)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)

        # Server list
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(180)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.currentItemChanged.connect(self._on_select)
        layout.addWidget(self.list_widget)

        # Scanning status
        self.scan_label = QLabel('Searching for servers on your network…')
        self.scan_label.setStyleSheet('color: grey;')
        layout.addWidget(self.scan_label)

        scan_btn = QPushButton('🔍  Search Again')
        scan_btn.clicked.connect(self._start_scan)
        layout.addWidget(scan_btn)

        # Manual entry
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        layout.addWidget(QLabel(
            'Server not listed? Enter its name or IP address:'
        ))
        self.manual_edit = QLineEdit()
        self.manual_edit.setPlaceholderText(
            'e.g.  192.168.1.2  or  mynas.local'
        )
        self.manual_edit.textChanged.connect(self.completeChanged)
        layout.addWidget(self.manual_edit)

        self.registerField('server_host*', self.manual_edit)

    def initializePage(self):
        self._start_scan()

    def _start_scan(self):
        self.scan_label.setText('Searching for servers on your network…')
        self.list_widget.clear()
        self._servers = []

        def worker():
            found = discover_servers()
            self._scan_complete.emit(found)

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_done(self, servers):
        self._servers = servers
        self.list_widget.clear()
        if servers:
            for name, ip in servers:
                item = QListWidgetItem(f'  {name}  ({ip})')
                item.setData(Qt.UserRole, ip)
                self.list_widget.addItem(item)
            self.scan_label.setText(
                f'Found {len(servers)} server(s). Click one to select it.'
            )
        else:
            self.scan_label.setText(
                'No servers found automatically. '
                'Enter a name or IP address below.'
            )

    def _on_select(self, item):
        if item:
            ip = item.data(Qt.UserRole)
            self.manual_edit.setText(ip)

    def isComplete(self):
        return bool(self.manual_edit.text().strip())


class WizardPageShare(QWizardPage):
    """
    Step 2 — Enter credentials (optional) then choose a share.

    Asks for credentials upfront rather than probing anonymously first.
    Both fields are optional — blank = anonymous access attempt.
    Credentials are forwarded to Step 3 so the user is never asked twice.
    """

    # Signals for thread-safe callbacks from background worker
    _shares_ready = pyqtSignal(object, str, str, str, str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle('Step 2 of 4 — Sign In and Choose a Folder')
        self.setSubTitle(
            'Enter your username and password if this server requires one, '
            'then click "Show Shared Folders". '
            'Leave both blank if the server is open to everyone.'
        )
        self._discovered_user = ''
        self._discovered_pass = ''
        self._shares_ready.connect(self._on_shares_loaded)
        self._build()

    def _build(self):
        # Outer layout holds credentials at top, then a scroll area for the rest
        outer = QVBoxLayout(self)
        outer.setSpacing(8)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Credentials (always visible, fixed at top) ────────────────────────
        cred_frame = QFrame()
        cred_frame.setFrameShape(QFrame.StyledPanel)
        cred_layout = QFormLayout(cred_frame)
        cred_layout.setLabelAlignment(Qt.AlignRight)
        cred_layout.setContentsMargins(8, 8, 8, 8)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText('username  (leave blank if not required)')
        cred_layout.addRow('Username:', self.user_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setPlaceholderText('password  (leave blank if not required)')
        self.pass_edit.returnPressed.connect(self._load_shares)
        cred_layout.addRow('Password:', self.pass_edit)

        load_btn = QPushButton('Show Shared Folders')
        load_btn.setMinimumHeight(32)
        load_btn.clicked.connect(self._load_shares)
        cred_layout.addRow('', load_btn)
        outer.addWidget(cred_frame)

        # ── Status label ──────────────────────────────────────────────────────
        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet('color: grey;')
        outer.addWidget(self.status_label)

        # ── Share list (expanding, takes available space) ─────────────────────
        self.list_widget = QListWidget()
        self.list_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.currentItemChanged.connect(self._on_select)
        self.list_widget.doubleClicked.connect(
            lambda: self.wizard().next() if self.isComplete() else None
        )
        outer.addWidget(self.list_widget, stretch=1)

        # ── Manual fallback ───────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        outer.addWidget(sep)
        outer.addWidget(QLabel('Folder not listed? Type its name here:'))

        self.manual_edit = QLineEdit()
        self.manual_edit.setPlaceholderText('e.g.  Documents  or  dhays')
        self.manual_edit.textChanged.connect(self.completeChanged)
        outer.addWidget(self.manual_edit)

        # ── Debug panel (hidden by default, shown only on failure) ────────────
        from PyQt5.QtWidgets import QPlainTextEdit
        self.debug_edit = QPlainTextEdit()
        self.debug_edit.setReadOnly(True)
        self.debug_edit.setFixedHeight(100)
        self.debug_edit.setStyleSheet(
            'font-family: monospace; font-size: 10px;'
        )
        self.debug_edit.setVisible(False)
        outer.addWidget(self.debug_edit)

        self.registerField('share_name*', self.manual_edit)

    def initializePage(self):
        host = self.field('server_host')
        self.list_widget.clear()
        self.manual_edit.clear()
        self._discovered_user = ''
        self._discovered_pass = ''
        self.status_label.setText(
            'Enter your credentials above then click '
            '"Show Shared Folders".\n'
            f'Connecting to: {host}'
        )

    def _load_shares(self):
        host     = self.field('server_host')
        username = self.user_edit.text().strip()
        password = self.pass_edit.text()

        self.status_label.setText('Loading shared folders…')
        self.list_widget.clear()
        self.debug_edit.clear()
        self.debug_edit.setVisible(True)
        self.debug_edit.setPlainText(
            f'Connecting to: {host}\n'
            f'Username: {username or "(none — anonymous)"}\n'
            f'Running smbclient...\n'
        )

        def worker():
            import subprocess as _sp
            import os as _os
            smbclient = _find_tool('smbclient')
            env = _tool_env()

            log.info('Share list attempt: host=%s user=%s tool=%s',
                     host, username or 'anon', smbclient)

            if username:
                cmd = [smbclient, '-L', host,
                       '-U', f'{username}%{password}',
                       '--option=client min protocol=SMB2']
            else:
                cmd = [smbclient, '-L', host, '-N',
                       '--option=client min protocol=SMB2']

            try:
                r = _sp.run(
                    cmd, capture_output=True, text=True,
                    timeout=15, env=env
                )
                stdout = r.stdout
                stderr = r.stderr
                rc     = r.returncode
            except FileNotFoundError as e:
                stdout = ''
                stderr = f'ERROR: smbclient not found: {e}'
                rc     = -1
            except _sp.TimeoutExpired:
                stdout = ''
                stderr = 'ERROR: Connection timed out after 15 seconds'
                rc     = -1
            except Exception as e:
                stdout = ''
                stderr = f'ERROR: {e}'
                rc     = -1

            log.info('smbclient rc=%s', rc)
            log.info('smbclient stdout: %s', stdout[:800])
            log.info('smbclient stderr: %s', stderr[:400])

            shares = _parse_shares(stdout)
            log.info('Parsed %d shares: %s', len(shares), shares)

            self._shares_ready.emit(shares, username, password,
                                       stdout, stderr, rc)

        threading.Thread(target=worker, daemon=True).start()

    def _on_shares_loaded(self, shares, username, password,
                          stdout, stderr, rc):
        if shares:
            self._discovered_user = username
            self._discovered_pass = password
            self._populate_list(shares)
            self.debug_edit.setVisible(False)
            self.status_label.setText(
                f'Found {len(shares)} shared folder(s). '
                f'Click one to select it, or type a name below.'
            )
        else:
            # Show debug panel only on failure
            debug_text = (
                f'Return code: {rc}\n\n'
                f'--- smbclient output ---\n{stdout}\n'
                f'--- stderr ---\n{stderr}'
            )
            self.debug_edit.setPlainText(debug_text)
            self.debug_edit.setVisible(True)
            self.status_label.setText(
                '❌  No shared folders found — see diagnostic output below.\n'
                'Check the server address and credentials, then try again.'
            )

    def _populate_list(self, shares):
        self.list_widget.clear()
        for s in shares:
            # Use text prefix instead of emoji — avoids font rendering issues
            item = QListWidgetItem(f'  [folder]  {s}')
            item.setData(Qt.UserRole, s)
            self.list_widget.addItem(item)

    def _on_select(self, item):
        if item:
            self.manual_edit.setText(item.data(Qt.UserRole))

    def isComplete(self):
        return bool(self.manual_edit.text().strip())


class WizardPageCredentials(QWizardPage):
    """Step 3 — Credentials."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle('Step 3 of 4 — Sign In')
        self.setSubTitle(
            'Does this shared folder require a username and password?'
        )
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Yes/No radio buttons — plain English
        self.no_radio  = QRadioButton(
            'No — this share is open to everyone on my network'
        )
        self.yes_radio = QRadioButton(
            'Yes — I need to sign in with a username and password'
        )
        self.no_radio.setChecked(True)
        self.no_radio.toggled.connect(self._on_toggle)
        layout.addWidget(self.no_radio)
        layout.addWidget(self.yes_radio)

        # Credential fields — hidden until "Yes" selected
        self.cred_frame = QFrame()
        self.cred_frame.setFrameShape(QFrame.StyledPanel)
        cred_layout = QFormLayout(self.cred_frame)
        cred_layout.setLabelAlignment(Qt.AlignRight)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText('your username')
        cred_layout.addRow('Username:', self.user_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setPlaceholderText('your password')
        cred_layout.addRow('Password:', self.pass_edit)

        self.save_check = QCheckBox(
            'Remember my password (stored securely in KWallet)'
        )
        self.save_check.setChecked(True)
        cred_layout.addRow('', self.save_check)

        layout.addWidget(self.cred_frame)
        self.cred_frame.setVisible(False)

        self.registerField('cred_required', self.yes_radio)
        self.registerField('username', self.user_edit)
        self.registerField('password', self.pass_edit)
        self.registerField('save_password', self.save_check)

    def initializePage(self):
        # If Step 2 collected credentials, pre-fill here so user isn't asked twice
        page_share = self.wizard().page_share
        if page_share._discovered_user:
            self.yes_radio.setChecked(True)
            self.user_edit.setText(page_share._discovered_user)
            self.pass_edit.setText(page_share._discovered_pass)
            self.cred_frame.setVisible(True)

    def _on_toggle(self):
        self.cred_frame.setVisible(self.yes_radio.isChecked())
        self.wizard().adjustSize()
        self.completeChanged.emit()

    def isComplete(self):
        if self.yes_radio.isChecked():
            return bool(self.user_edit.text().strip())
        return True


class WizardPageOptions(QWizardPage):
    """Step 4 — Name it and set options."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle('Step 4 of 4 — Name and Options')
        self.setSubTitle(
            'Give this connection a name so you can recognise it. '
            'The optional settings below work for most home networks — '
            'you can leave them as they are.'
        )
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Mount name
        name_frame = QFrame()
        name_frame.setFrameShape(QFrame.StyledPanel)
        name_layout = QFormLayout(name_frame)
        name_layout.setLabelAlignment(Qt.AlignRight)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('e.g.  My NAS  or  Home Files')
        self.name_edit.setMaxLength(32)
        name_layout.addRow('Connection name:', self.name_edit)
        layout.addWidget(name_frame)

        self.registerField('mount_label*', self.name_edit)

        # Optional settings — collapsible group
        opt_group = QGroupBox('Optional Settings  (most users can leave these as-is)')
        opt_group.setCheckable(False)
        opt_layout = QFormLayout(opt_group)
        opt_layout.setLabelAlignment(Qt.AlignRight)

        # SMB version
        self.smb_version = QComboBox()
        self.smb_version.addItems([
            'Automatic  (recommended)',
            'SMB 3  (modern NAS, Windows 10+)',
            'SMB 2  (older devices)',
        ])
        opt_layout.addRow('Compatibility:', self.smb_version)

        # Auto-connect
        self.autoconnect = QCheckBox('Connect automatically when I log in')
        self.autoconnect.setChecked(True)
        opt_layout.addRow('', self.autoconnect)

        # Read only
        self.readonly = QCheckBox(
            'Read only  (prevent accidental changes to files)'
        )
        self.readonly.setChecked(False)
        opt_layout.addRow('', self.readonly)

        layout.addWidget(opt_group)
        layout.addStretch()

    def initializePage(self):
        # Pre-fill name from share name
        share = self.field('share_name')
        if share and not self.name_edit.text():
            self.name_edit.setText(share)

    def get_options(self) -> str:
        """Build the options string from GUI selections."""
        parts = []
        idx = self.smb_version.currentIndex()
        if idx == 1:
            parts.append('vers=3.0')
        elif idx == 2:
            parts.append('vers=2.0')
        if not self.autoconnect.isChecked():
            # Remove _netdev,nofail equivalent — just omit auto flags
            pass
        if self.readonly.isChecked():
            parts.append('ro')
        return ','.join(parts)

    def isComplete(self):
        return bool(self.name_edit.text().strip())


class SimpleWizard(QWizard):
    """
    Guided four-step wizard for adding a network share.
    No technical knowledge required.
    """
    mount_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Tether {VERSION}')
        self.setMinimumSize(580, 540)
        self.resize(600, 600)
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)

        self.page_server  = WizardPageServer(self)
        self.page_share   = WizardPageShare(self)
        self.page_creds   = WizardPageCredentials(self)
        self.page_options = WizardPageOptions(self)

        self.addPage(self.page_server)
        self.addPage(self.page_share)
        self.addPage(self.page_creds)
        self.addPage(self.page_options)

        self.setButtonText(QWizard.FinishButton, 'Connect')
        self.accepted.connect(self._on_accepted)

    def _on_accepted(self):
        host     = self.field('server_host').strip()
        share    = self.field('share_name').strip()
        label    = self.field('mount_label').strip()
        username = self.field('username').strip()
        password = self.field('password')
        save_pw  = self.field('save_password')
        options  = self.page_options.get_options()

        # Sanitize label — remove spaces, special chars
        import re
        label = re.sub(r'[^a-zA-Z0-9_\-]', '_', label)[:32]

        self.mount_requested.emit({
            'label':     label,
            'protocol':  'cifs',
            'host':      host,
            'path':      share,
            'options':   options,
            'username':  username,
            'password':  password,
            'save_creds': save_pw and bool(username),
        })


# ═══════════════════════════════════════════════════════════════════════════════
# ADVANCED DIALOG (original form, for power users)
# ═══════════════════════════════════════════════════════════════════════════════

class AdvancedMountDialog(QDialog):
    """Original technical form — for users who know what they're doing."""

    _PROTO_MAP = {
        'SMB / CIFS  (Windows shares, NAS)': 'cifs',
        'NFS  (Linux/Unix shares)':           'nfs',
        'SSHFS  (SSH file system)':           'sshfs',
    }
    _PROTO_HINTS = {
        'SMB / CIFS  (Windows shares, NAS)':
            'Use for Windows PCs, Samba, and most NAS devices.',
        'NFS  (Linux/Unix shares)':
            'Use for Linux servers. Usually no credentials needed.',
        'SSHFS  (SSH file system)':
            'Mounts over SSH. Works on any server you can SSH into.',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Tether – Add Mount (Advanced)')
        self.setMinimumWidth(480)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)

        detail_box = QFrame()
        detail_box.setFrameShape(QFrame.StyledPanel)
        form = QFormLayout(detail_box)
        form.setLabelAlignment(Qt.AlignRight)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText('my-nas')
        self.label_edit.setMaxLength(32)
        form.addRow('Label:', self.label_edit)

        self.proto_combo = QComboBox()
        self.proto_combo.addItems(list(self._PROTO_MAP.keys()))
        self.proto_combo.currentTextChanged.connect(self._on_proto_change)
        form.addRow('Protocol:', self.proto_combo)

        self.proto_hint = QLabel()
        self.proto_hint.setWordWrap(True)
        self.proto_hint.setStyleSheet('color: grey; font-size: 11px;')
        form.addRow('', self.proto_hint)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText('192.168.1.2  or  hostname')
        form.addRow('Host:', self.host_edit)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText('ShareName')
        form.addRow('Share / Path:', self.path_edit)

        # SMB version selector replaces free-text options for CIFS
        self.smb_version_combo = QComboBox()
        self.smb_version_combo.addItems([
            'Automatic  (recommended)',
            'SMB 3  (modern)',
            'SMB 2  (older devices)',
            'SMB 1  (legacy — insecure)',
        ])
        self.smb_version_row_label = QLabel('SMB Version:')
        form.addRow(self.smb_version_row_label, self.smb_version_combo)

        self.readonly_check = QCheckBox('Mount read-only')
        form.addRow('', self.readonly_check)

        self.opts_edit = QLineEdit()
        self.opts_edit.setPlaceholderText('uid=1000  (advanced — optional)')
        form.addRow('Extra Options:', self.opts_edit)

        root.addWidget(detail_box)

        self.cred_frame = QFrame()
        self.cred_frame.setFrameShape(QFrame.StyledPanel)
        cred_layout = QFormLayout(self.cred_frame)
        cred_layout.setLabelAlignment(Qt.AlignRight)
        cred_layout.addRow(QLabel('<b>Credentials</b>'))

        self.user_edit = QLineEdit()
        cred_layout.addRow('Username:', self.user_edit)

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        cred_layout.addRow('Password:', self.pass_edit)
        root.addWidget(self.cred_frame)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        QPushButton('Cancel', clicked=self.reject).setParent(self)
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        mount = QPushButton('Mount')
        mount.setDefault(True)
        mount.clicked.connect(self._validate_and_accept)
        btn_row.addWidget(cancel)
        btn_row.addWidget(mount)
        root.addLayout(btn_row)

        self._on_proto_change(self.proto_combo.currentText())

    def _on_proto_change(self, display: str):
        internal = self._PROTO_MAP.get(display, 'cifs')
        is_cifs  = internal == 'cifs'
        self.cred_frame.setVisible(internal in ('cifs', 'sshfs'))
        self.smb_version_combo.setVisible(is_cifs)
        self.smb_version_row_label.setVisible(is_cifs)
        self.proto_hint.setText(self._PROTO_HINTS.get(display, ''))
        if internal == 'nfs':
            self.path_edit.setPlaceholderText('/export/path')
        elif internal == 'sshfs':
            self.path_edit.setPlaceholderText('/home/username')
        else:
            self.path_edit.setPlaceholderText('ShareName')
        self.adjustSize()

    def _get_options(self) -> str:
        parts = []
        idx = self.smb_version_combo.currentIndex()
        version_map = {1: 'vers=3.0', 2: 'vers=2.0', 3: 'vers=1.0'}
        if idx in version_map:
            parts.append(version_map[idx])
        if self.readonly_check.isChecked():
            parts.append('ro')
        extra = self.opts_edit.text().strip()
        if extra:
            parts.append(extra)
        return ','.join(parts)

    def _validate_and_accept(self):
        problems = []
        if not self.label_edit.text().strip():
            problems.append('Label is required.')
        if not self.host_edit.text().strip():
            problems.append('Host is required.')
        if not self.path_edit.text().strip():
            problems.append('Share / Path is required.')
        if problems:
            QMessageBox.warning(self, 'Tether', '\n'.join(problems))
            return
        self.accept()

    def values(self) -> dict:
        display  = self.proto_combo.currentText()
        internal = self._PROTO_MAP.get(display, 'cifs')
        return {
            'label':     self.label_edit.text().strip(),
            'protocol':  internal,
            'host':      self.host_edit.text().strip(),
            'path':      self.path_edit.text().strip(),
            'options':   self._get_options(),
            'username':  self.user_edit.text().strip(),
            'password':  self.pass_edit.text(),
            'save_creds': bool(self.user_edit.text().strip()),
        }


# ── Transfer card ─────────────────────────────────────────────────────────────

class TransferCard(QFrame):

    def __init__(self, job_id, info, client, on_dismiss=None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.job_id       = job_id
        self.client       = client
        self._on_dismiss  = on_dismiss
        self._last_status = info.get('status', '')
        self._build(info)

    def _build(self, info):
        layout = QVBoxLayout(self)

        # Title row with dismiss X button
        title_row = QHBoxLayout()
        title = QLabel(
            f"<b>{info.get('src','?')}</b>  →  <b>{info.get('dst','?')}</b>"
        )
        title.setWordWrap(True)
        title_row.addWidget(title, stretch=1)

        self._dismiss_btn = QPushButton('✕')
        self._dismiss_btn.setFixedSize(24, 24)
        self._dismiss_btn.setFlat(True)
        self._dismiss_btn.setToolTip('Remove from list')
        self._dismiss_btn.setVisible(False)
        self._dismiss_btn.clicked.connect(
            lambda: self._on_dismiss() if self._on_dismiss else None
        )
        title_row.addWidget(self._dismiss_btn)
        layout.addLayout(title_row)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        layout.addWidget(self.bar)

        row = QHBoxLayout()
        self.status_lbl = QLabel()
        self.speed_lbl  = QLabel()
        self.eta_lbl    = QLabel()
        row.addWidget(self.status_lbl)
        row.addStretch()
        row.addWidget(self.speed_lbl)
        row.addWidget(self.eta_lbl)
        layout.addLayout(row)

        btn_row = QHBoxLayout()
        self._pause_btn  = QPushButton('Pause')
        self._resume_btn = QPushButton('Resume')
        self._cancel_btn = QPushButton('Cancel')
        self._pause_btn.setFixedWidth(80)
        self._resume_btn.setFixedWidth(80)
        self._cancel_btn.setFixedWidth(80)
        self._pause_btn.clicked.connect(
            lambda: self.client.pause_transfer(self.job_id))
        self._resume_btn.clicked.connect(
            lambda: self.client.resume_transfer(self.job_id))
        self._cancel_btn.clicked.connect(
            lambda: self.client.cancel_transfer(self.job_id))
        btn_row.addWidget(self._pause_btn)
        btn_row.addWidget(self._resume_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.refresh(info)

    def refresh(self, info):
        status  = info.get('status', '')
        running = status == 'running'
        paused  = status == 'paused'
        done    = status in ('done', 'failed')

        self.bar.setValue(info.get('progress', 0))

        status_labels = {
            'queued':  'Waiting to start…',
            'running': 'Transferring…',
            'paused':  'Paused',
            'done':    'Complete ✓',
            'failed':  'Failed ✗',
        }
        # Show unambiguous dry run labels
        speed = info.get('speed', '')
        eta   = info.get('eta', '')
        is_dry = 'dry run' in speed.lower() or 'dry run' in eta.lower()

        if is_dry and status == 'running':
            display_status = 'Dry run — previewing files, nothing is being copied'
        elif is_dry and status == 'done':
            display_status = 'Dry run complete — no files were copied'
        elif is_dry and status == 'failed':
            display_status = 'Dry run failed'
        else:
            display_status = status_labels.get(status, status.capitalize())

        self.status_lbl.setText(display_status)
        self.speed_lbl.setText('' if is_dry else speed)
        self.eta_lbl.setText('' if is_dry else (f'ETA {eta}' if eta else ''))

        self._last_status = status
        running = status == 'running'
        paused  = status == 'paused'
        done    = status in ('done', 'failed')

        # Show dismiss X when finished, hide control buttons
        self._dismiss_btn.setVisible(done)
        self._pause_btn.setEnabled(running)
        self._resume_btn.setEnabled(paused)
        self._cancel_btn.setEnabled(not done)


# ── New Transfer dialog ───────────────────────────────────────────────────────

class NewTransferDialog(QDialog):
    """
    Simple dialog for starting an rsync file transfer.
    All rsync options presented as plain-English checkboxes.
    No command line required.
    """

    def __init__(self, parent, mounts: dict):
        super().__init__(parent)
        self.setWindowTitle('Tether – New File Transfer')
        self.setMinimumWidth(560)
        self._mounts = mounts   # {label: info} of currently mounted shares
        self._build()

    def _path_selector(self, layout, label_text: str, edit_attr: str):
        """
        Build a source/destination selector with:
          - Dropdown showing mounted shares + "My Computer (browse...)"
          - Path text field (editable, updated when dropdown changes)
          - Browse button for drilling into subfolders
        """
        layout.addWidget(QLabel(f'<b>{label_text}</b>'))

        # Dropdown — mounted shares at top, local browse at bottom
        combo = QComboBox()
        combo.addItem('-- My Computer (browse for a folder) --', userData='')
        for lbl, info in self._mounts.items():
            if info.get('mounted'):
                mp = info.get('mountpoint', f'/mnt/{lbl}')
                combo.addItem(
                    f'[Network]  {lbl}  ({info.get("host","")}/{info.get("remote_path","")})',
                    userData=mp
                )
        combo.insertSeparator(1)  # separator after "My Computer"
        layout.addWidget(combo)

        # Path field + Browse button
        path_row = QHBoxLayout()
        edit = QLineEdit()
        edit.setPlaceholderText('Select from the list above or Browse…')
        path_row.addWidget(edit)
        browse_btn = QPushButton('Browse…')
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(lambda: self._browse(edit))
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        # When dropdown changes, update the path field
        def on_combo_change(index):
            mp = combo.itemData(index)
            if mp:
                edit.setText(mp)
            else:
                # "My Computer" selected — open folder picker immediately
                self._browse(edit)
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)

        combo.currentIndexChanged.connect(on_combo_change)

        # Store refs
        setattr(self, edit_attr, edit)
        setattr(self, edit_attr + '_combo', combo)

    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ── Source and destination ────────────────────────────────────────────
        paths_frame = QFrame()
        paths_frame.setFrameShape(QFrame.StyledPanel)
        paths_layout = QVBoxLayout(paths_frame)
        paths_layout.setSpacing(10)

        self._path_selector(paths_layout, 'Copy from (source):', 'src_edit')
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        paths_layout.addWidget(sep)
        self._path_selector(paths_layout, 'Copy to (destination):', 'dst_edit')
        root.addWidget(paths_frame)

        # ── Options ───────────────────────────────────────────────────────────
        opts_group = QGroupBox('Transfer Options')
        opts_layout = QVBoxLayout(opts_group)

        self.opt_resume = QCheckBox(
            'Resume interrupted transfers  '
            '(picks up where it left off if the transfer is stopped)'
        )
        self.opt_resume.setChecked(True)
        opts_layout.addWidget(self.opt_resume)

        self.opt_skip_newer = QCheckBox(
            'Skip files that are already up to date at the destination'
        )
        self.opt_skip_newer.setChecked(False)
        opts_layout.addWidget(self.opt_skip_newer)

        self.opt_compress = QCheckBox(
            'Compress data during transfer  '
            '(useful on slow or wireless connections, slower on fast LAN)'
        )
        self.opt_compress.setChecked(False)
        opts_layout.addWidget(self.opt_compress)

        self.opt_perms = QCheckBox(
            'Preserve file permissions and ownership'
        )
        self.opt_perms.setChecked(False)
        opts_layout.addWidget(self.opt_perms)

        self.opt_delete = QCheckBox(
            'Delete files at destination that no longer exist at source  '
            '(use for keeping an exact mirror — cannot be undone)'
        )
        self.opt_delete.setChecked(False)
        # Warn user when they enable delete
        self.opt_delete.toggled.connect(self._on_delete_toggled)
        opts_layout.addWidget(self.opt_delete)

        self.opt_dry_run = QCheckBox(
            'Dry run — show what WOULD be transferred without actually doing it'
        )
        self.opt_dry_run.setChecked(False)
        opts_layout.addWidget(self.opt_dry_run)

        root.addWidget(opts_group)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        start = QPushButton('Start Transfer')
        start.setDefault(True)
        start.clicked.connect(self._validate_and_accept)
        btn_row.addWidget(cancel)
        btn_row.addWidget(start)
        root.addLayout(btn_row)

    def _browse(self, edit: QLineEdit):
        from PyQt5.QtWidgets import QFileDialog
        start = edit.text() or '/'
        path  = QFileDialog.getExistingDirectory(
            self, 'Select Folder', start
        )
        if path:
            edit.setText(path)

    def _on_delete_toggled(self, checked: bool):
        if checked:
            reply = QMessageBox.warning(
                self, 'Tether – Delete Option',
                'The "Delete" option will permanently remove files at the '
                'destination that do not exist at the source.\n\n'
                'This cannot be undone. Are you sure?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.opt_delete.setChecked(False)

    def _validate_and_accept(self):
        src = self.src_edit.text().strip()
        dst = self.dst_edit.text().strip()
        problems = []
        if not src:
            problems.append('Source path is required.')
        if not dst:
            problems.append('Destination path is required.')
        if src == dst:
            problems.append('Source and destination cannot be the same.')
        if problems:
            QMessageBox.warning(self, 'Tether', '\n'.join(problems))
            return
        self.accept()

    def values(self) -> dict:
        return {
            'source':        self.src_edit.text().strip(),
            'destination':   self.dst_edit.text().strip(),
            'resume':        self.opt_resume.isChecked(),
            'skip_newer':    self.opt_skip_newer.isChecked(),
            'compress':      self.opt_compress.isChecked(),
            'preserve_perms': self.opt_perms.isChecked(),
            'delete':        self.opt_delete.isChecked(),
            'dry_run':       self.opt_dry_run.isChecked(),
        }


# ── Main management window ────────────────────────────────────────────────────

class TetherWindow(QDialog):

    def __init__(self, client):
        super().__init__()
        self.client         = client
        self._xfer_cards    = {}
        self._mount_widgets = []
        self.setWindowTitle(f'Tether {VERSION} – Network Connections')
        self.setMinimumSize(620, 480)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)

        # ── Menu bar row ──────────────────────────────────────────────────────
        menu_row = QHBoxLayout()
        menu_row.addStretch()

        options_btn = QPushButton('⚙  Options')
        options_btn.setFlat(True)
        options_btn.clicked.connect(self._show_options_menu)
        menu_row.addWidget(options_btn)
        root.addLayout(menu_row)

        # ── Tabs ──────────────────────────────────────────────────────────────
        tabs = QTabWidget()
        root.addWidget(tabs)

        # Mounts tab
        mounts_page   = QWidget()
        mounts_layout = QVBoxLayout(mounts_page)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._mounts_inner = QWidget()
        self._mounts_vbox  = QVBoxLayout(self._mounts_inner)
        self._mounts_vbox.setAlignment(Qt.AlignTop)
        scroll.setWidget(self._mounts_inner)
        mounts_layout.addWidget(scroll)

        connect_btn = QPushButton('+  Connect to Network Share…')
        connect_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        connect_btn.setMinimumHeight(36)
        connect_btn.clicked.connect(self._on_add)
        mounts_layout.addWidget(connect_btn)
        tabs.addTab(mounts_page, 'Network Connections')

        # Transfers tab
        xfer_page   = QWidget()
        xfer_layout = QVBoxLayout(xfer_page)

        xfer_scroll = QScrollArea()
        xfer_scroll.setWidgetResizable(True)
        self._xfer_inner = QWidget()
        self._xfer_vbox  = QVBoxLayout(self._xfer_inner)
        self._xfer_vbox.setAlignment(Qt.AlignTop)
        xfer_scroll.setWidget(self._xfer_inner)
        xfer_layout.addWidget(xfer_scroll)

        # Bottom button row
        btn_row = QHBoxLayout()
        new_xfer_btn = QPushButton('+  New File Transfer…')
        new_xfer_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        new_xfer_btn.setMinimumHeight(36)
        new_xfer_btn.clicked.connect(self._on_new_transfer)
        btn_row.addWidget(new_xfer_btn)

        clear_btn = QPushButton('Clear History')
        clear_btn.setFixedWidth(120)
        clear_btn.setMinimumHeight(36)
        clear_btn.setToolTip('Remove all completed transfers from this list')
        clear_btn.clicked.connect(self._clear_transfer_history)
        btn_row.addWidget(clear_btn)
        xfer_layout.addLayout(btn_row)
        tabs.addTab(xfer_page, 'File Transfers')

    def _on_new_transfer(self):
        # Get currently mounted shares to populate the dropdowns
        try:
            mounts = self.client.list_mounts()
        except Exception:
            mounts = {}
        dlg = NewTransferDialog(self, mounts)
        if dlg.exec_() != QDialog.Accepted:
            return
        v = dlg.values()

        # Build rsync options from checkboxes
        opts = []
        if v['resume']:        opts.append('--partial')
        if v['delete']:        opts.append('--delete')
        if v['preserve_perms']:opts.append('--perms')
        if v['skip_newer']:    opts.append('--update')
        if v['compress']:      opts.append('--compress')
        if v['dry_run']:       opts.append('--dry-run')

        src = v['source']
        dst = v['destination']

        if not src or not dst:
            QMessageBox.warning(self, 'Tether',
                                'Source and destination are required.')
            return

        result = self.client.start_transfer(src, dst, opts)

        if result.startswith('ERROR'):
            QMessageBox.critical(
                self, 'Transfer Failed',
                f'Could not start transfer.\n\n{result}'
            )
        else:
            if v['dry_run']:
                QMessageBox.information(
                    self, 'Tether – Dry Run Started',
                    'Dry run started.\n\n'
                    'Tether will show which files WOULD be transferred '
                    'without actually copying anything.\n\n'
                    'Check the log for the full file list:\n'
                    '~/.local/share/tether/tether.log'
                )

    def _show_options_menu(self):
        menu = QMenu(self)

        advanced = QAction('Advanced Mode  (for power users)', self)
        advanced.setCheckable(True)
        advanced.setChecked(_get_advanced_mode())
        advanced.triggered.connect(self._toggle_advanced)
        menu.addAction(advanced)

        menu.addSeparator()
        about = QAction(f'About Tether {VERSION}', self)
        about.triggered.connect(self._show_about)
        menu.addAction(about)

        menu.exec_(self.sender().mapToGlobal(
            self.sender().rect().bottomLeft()
        ))

    def _toggle_advanced(self, checked: bool):
        _set_advanced_mode(checked)
        mode = 'Advanced Mode' if checked else 'Simple Mode'
        QMessageBox.information(
            self, 'Tether',
            f'{mode} enabled.\n\n'
            f'This will take effect the next time you click '
            f'"Connect to Network Share".'
        )

    def _show_about(self):
        QMessageBox.about(
            self, f'Tether {VERSION}',
            f'<b>Tether {VERSION}</b><br>'
            f'Network Mount Manager for KDE / CachyOS<br><br>'
            f'Makes connecting to network shares as easy as Windows.<br><br>'
            f'License: GPL v3'
        )

    # ── mount updates ─────────────────────────────────────────────────────────

    def update_mounts(self, mounts: dict):
        for w in self._mount_widgets:
            self._mounts_vbox.removeWidget(w)
            w.deleteLater()
        self._mount_widgets.clear()

        if not mounts:
            lbl = QLabel(
                'No network connections yet.\n\n'
                'Click "Connect to Network Share" to get started.'
            )
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet('color: grey; padding: 20px;')
            self._mounts_vbox.addWidget(lbl)
            self._mount_widgets.append(lbl)
            return

        for label, info in mounts.items():
            dot   = '🟢' if info.get('mounted') else '🔴'
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            row   = QHBoxLayout(frame)

            # Friendly display — hide technical details by default
            host  = info.get('host', '')
            share = info.get('remote_path', '')
            text  = QLabel(
                f'{dot}  <b>{label}</b>'
                f'<br><small style="color:grey;">'
                f'{host} / {share}'
                f'  —  {info["mountpoint"]}</small>'
            )
            text.setWordWrap(True)
            row.addWidget(text, stretch=1)

            disconnect = QPushButton('Disconnect')
            disconnect.setFixedWidth(100)
            disconnect.clicked.connect(
                lambda _, l=label: self._on_remove(l)
            )
            row.addWidget(disconnect)

            self._mounts_vbox.addWidget(frame)
            self._mount_widgets.append(frame)

    # ── transfer updates ──────────────────────────────────────────────────────

    def _clear_transfer_history(self):
        """Remove all completed/failed transfers from display and daemon."""
        to_remove = []
        for jid, card in list(self._xfer_cards.items()):
            if card._last_status in ('done', 'failed'):
                to_remove.append(jid)

        if not to_remove:
            QMessageBox.information(
                self, 'Tether',
                'No completed transfers to clear.\n\n'
                'Active transfers are kept until they finish.'
            )
            return

        for jid in to_remove:
            self.client.remove_transfer(jid)
            card = self._xfer_cards.pop(jid)
            self._xfer_vbox.removeWidget(card)
            card.deleteLater()

    def _dismiss_transfer(self, jid: str):
        """Remove a single transfer card from display and daemon."""
        self.client.remove_transfer(jid)
        card = self._xfer_cards.pop(jid, None)
        if card:
            self._xfer_vbox.removeWidget(card)
            card.deleteLater()

    def update_transfers(self, transfers: dict):
        for jid, info in transfers.items():
            if jid in self._xfer_cards:
                self._xfer_cards[jid].refresh(info)
            else:
                card = TransferCard(
                    jid, info, self.client,
                    on_dismiss=lambda j=jid: self._dismiss_transfer(j),
                    parent=self._xfer_inner,
                )
                self._xfer_vbox.addWidget(card)
                self._xfer_cards[jid] = card

    # ── actions ───────────────────────────────────────────────────────────────

    def _on_add(self):
        if _get_advanced_mode():
            self._add_advanced()
        else:
            self._add_wizard()

    def _add_wizard(self):
        wizard = SimpleWizard(self)
        wizard.mount_requested.connect(self._do_mount)
        wizard.exec_()

    def _add_advanced(self):
        dlg = AdvancedMountDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            self._do_mount(dlg.values())

    def _do_mount(self, values: dict):
        """Shared mount logic for both wizard and advanced dialog."""
        label    = values['label']
        username = values.get('username', '')
        password = values.get('password', '')

        cred_saved = False
        if values.get('save_creds') and username:
            try:
                from credentials import save_credentials
                save_credentials(label, username, password)
                cred_saved = True
            except Exception as e:
                log.warning('Credential save failed: %s', e)

        result = self.client.add_mount(
            label,
            values.get('protocol', 'cifs'),
            values.get('host', ''),
            values.get('path', ''),
            values.get('options', ''),
            label,
            username,
            password,
        )

        if result.startswith('ERROR'):
            if cred_saved:
                try:
                    from credentials import delete_credentials
                    delete_credentials(label)
                except Exception:
                    pass
            QMessageBox.critical(
                self, 'Connection Failed',
                f'Could not connect to {label}.\n\n{result}\n\n'
                f'Check that the server is online and your '
                f'credentials are correct.'
            )
        else:
            QMessageBox.information(
                self, 'Connected',
                f'Successfully connected to {label}.\n\n'
                f'You can find it at /mnt/{label} '
                f'or in Dolphin under Network.'
            )

    def _on_remove(self, label: str):
        reply = QMessageBox.question(
            self, 'Disconnect',
            f'Disconnect from {label}?\n\n'
            f'Any open files on this share should be closed first.',
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return
        result = self.client.remove_mount(label)
        if result.startswith('ERROR'):
            QMessageBox.critical(self, 'Tether', result)


# ── System tray ───────────────────────────────────────────────────────────────

class TetherTray(QSystemTrayIcon):

    def __init__(self, app, client):
        icon = QIcon.fromTheme(
            'network-server',
            app.style().standardIcon(app.style().SP_DriveNetIcon)
        )
        super().__init__(icon, app)
        self.client = client
        self.window = TetherWindow(client)
        self._build_menu()
        self.setToolTip(f'Tether {VERSION} – Network Connections')
        self.activated.connect(self._on_activate)

    def _build_menu(self):
        menu = QMenu()
        menu.addAction('Open Tether…', self._show_window)
        menu.addAction('Connect to Share…', self.window._on_add)
        menu.addSeparator()
        self._status_item = menu.addAction('No connections')
        self._status_item.setEnabled(False)
        menu.addSeparator()
        menu.addAction('Quit Tether', QApplication.instance().quit)
        self.setContextMenu(menu)

    def _show_window(self):
        self.window.show()
        self.window.raise_()

    def _on_activate(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.window.isVisible():
                self.window.hide()
            else:
                self._show_window()

    def on_mounts_updated(self, mounts: dict):
        self.window.update_mounts(mounts)
        connected = sum(1 for m in mounts.values() if m.get('mounted'))
        total     = len(mounts)
        tip = (f'Tether {VERSION} – {connected}/{total} connected'
               if total else f'Tether {VERSION} – No connections')
        self.setToolTip(tip)
        self._status_item.setText(
            f'{connected}/{total} connected' if total else 'No connections'
        )

    def on_transfers_updated(self, transfers: dict):
        self.window.update_transfers(transfers)

    def on_poll_error(self, msg: str):
        log.warning('Poll error: %s', msg)


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    import os
    if os.environ.get('WAYLAND_DISPLAY'):
        os.environ.setdefault('QT_QPA_PLATFORM', 'wayland')

    app = QApplication(sys.argv)
    app.setApplicationName('Tether')
    app.setApplicationDisplayName(f'Tether {VERSION}')
    app.setDesktopFileName('tether')
    app.setQuitOnLastWindowClosed(False)

    from client import TetherClient
    try:
        client = TetherClient()
    except RuntimeError as e:
        QMessageBox.critical(None, 'Tether – Startup Error', str(e))
        sys.exit(1)

    tray = TetherTray(app, client)
    tray.show()

    poller = DaemonPoller()
    poller.mounts_ready.connect(tray.on_mounts_updated)
    poller.transfers_ready.connect(tray.on_transfers_updated)
    poller.error_occurred.connect(tray.on_poll_error)
    poller.start()

    ret = app.exec_()
    poller.stop()
    sys.exit(ret)


if __name__ == '__main__':
    run()
