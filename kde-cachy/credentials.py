#!/usr/bin/env python3
"""
Tether — KDE/CachyOS Edition
Credential Manager

KDE target means KWallet is always available.
Backend priority:
  1. KWallet  (primary — always present on KDE Plasma)
  2. File     (fallback — plaintext JSON chmod 600, for edge cases)

libsecret / GNOME Keyring intentionally omitted — not relevant on KDE.

Security:
  - KWallet data passed via temp file where possible
  - File backend uses atomic write (write-then-rename) at chmod 600
  - write_samba_cred_file() uses shlex.quote() for all shell args
  - No user data ever interpolated into shell -c strings
"""

VERSION = '0.7.9'

import os
import json
import shlex
import logging
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger('tether.credentials')

CRED_DIR = Path.home() / '.local' / 'share' / 'tether' / 'credentials'
FOLDER   = 'tether-mounts'


# ── KWallet backend ───────────────────────────────────────────────────────────

class KWalletBackend:
    """
    Primary backend for KDE Plasma.
    Uses kwallet-query CLI. Passwords are passed as CLI args — a known
    limitation of kwallet-query. For a fully ps-safe path the KWallet
    D-Bus API should be used directly; that is a planned future improvement.
    """

    def available(self) -> bool:
        try:
            r = subprocess.run(
                ['kwallet-query', '--list-wallets'],
                capture_output=True, text=True, timeout=5
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def save(self, label: str, username: str, password: str) -> None:
        payload = json.dumps({'username': username, 'password': password})
        subprocess.run(
            ['kwallet-query', '-w', payload, '-f', FOLDER, 'kdewallet', label],
            check=True, capture_output=True, timeout=10
        )

    def load(self, label: str) -> dict:
        r = subprocess.run(
            ['kwallet-query', '-r', '-f', FOLDER, 'kdewallet', label],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            try:
                return json.loads(r.stdout.strip())
            except (json.JSONDecodeError, ValueError):
                log.warning('KWallet returned non-JSON for %r', label)
        return {}

    def delete(self, label: str) -> None:
        subprocess.run(
            ['kwallet-query', '-d', '-f', FOLDER, 'kdewallet', label],
            capture_output=True, timeout=10
        )


# ── File fallback backend ─────────────────────────────────────────────────────

class FileBackend:
    """
    Plaintext JSON at chmod 600.
    WARNING: credentials are NOT encrypted at rest.
    Used only when KWallet is unavailable (headless, minimal install).
    """

    def available(self) -> bool:
        return True

    def _ensure_dir(self) -> None:
        CRED_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(CRED_DIR, 0o700)

    def _path(self, label: str) -> Path:
        self._ensure_dir()
        return CRED_DIR / f'{label}.json'

    def save(self, label: str, username: str, password: str) -> None:
        self._ensure_dir()
        path = self._path(label)
        data = json.dumps({'username': username, 'password': password})
        # Atomic write: temp → rename
        fd, tmp = tempfile.mkstemp(dir=CRED_DIR, prefix=f'.{label}_')
        try:
            os.chmod(tmp, 0o600)
            os.write(fd, data.encode('utf-8'))
            os.close(fd)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def load(self, label: str) -> dict:
        path = self._path(label)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError) as e:
                log.error('Credential read error for %r: %s', label, e)
        return {}

    def delete(self, label: str) -> None:
        path = self._path(label)
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            log.error('Credential delete error for %r: %s', label, e)


# ── Detection and public API ──────────────────────────────────────────────────

_backend = None


def _get_backend():
    global _backend
    if _backend is None:
        for cls in (KWalletBackend, FileBackend):
            b = cls()
            if b.available():
                log.info('Credential backend: %s', type(b).__name__)
                _backend = b
                break
    return _backend


def save_credentials(label: str, username: str, password: str) -> None:
    _get_backend().save(label, username, password)


def load_credentials(label: str) -> dict:
    return _get_backend().load(label)


def delete_credentials(label: str) -> None:
    _get_backend().delete(label)


def write_samba_cred_file(label: str, username: str, password: str) -> str:
    """
    Write /etc/samba/.tether_<label> via pkexec.
    Returns the path on success.
    Security: credentials go to a chmod 600 temp file; path passed via
    shlex.quote() — no user data in any shell -c string.
    """
    import re as _re
    safe_label = _re.sub(r'[^a-zA-Z0-9_\-]', '_', str(label))[:32].strip('_') or 'mount'
    cred_path  = f'/etc/samba/.tether_{safe_label}'
    content    = f'username={username}\npassword={password}\n'

    fd, tmp = tempfile.mkstemp(prefix='tether_smb_')
    try:
        os.chmod(tmp, 0o600)
        os.write(fd, content.encode('utf-8'))
        os.close(fd)

        script = '\n'.join([
            '#!/bin/bash',
            'set -euo pipefail',
            f'install -m 600 -o root -g root {shlex.quote(tmp)} {shlex.quote(cred_path)}',
        ]) + '\n'

        fd2, spath = tempfile.mkstemp(suffix='.sh', prefix='tether_smb_')
        try:
            os.chmod(spath, 0o700)
            os.write(fd2, script.encode('utf-8'))
            os.close(fd2)
            r = subprocess.run(
                ['pkexec', 'bash', spath],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip())
            return cred_path
        finally:
            try:
                os.unlink(spath)
            except OSError:
                pass
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
