#!/usr/bin/env python3
"""
Tether — KDE/CachyOS Edition
Core D-Bus Daemon

Focused version for KDE Plasma on Wayland, CachyOS (Arch-based).

Security model:
  - Session D-Bus only; mountpoints strictly constrained to /mnt/<label>
  - All privileged operations run via pkexec helper scripts written to
    mkstemp() paths, chmod 700 before any content is written
  - User-supplied strings never interpolated into shell -c arguments
  - shlex.quote() used wherever any string touches a shell command
  - Host/path inputs validated against a blocklist of shell metacharacters
"""

VERSION = '0.7.9'

import re
import os
import sys
import json
import shlex
import signal
import socket
import logging
import tempfile
import subprocess
import threading
import time
from pathlib import Path

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

# ── logging ───────────────────────────────────────────────────────────────────
# Directory created before basicConfig so FileHandler never fails on first run
_TETHER_DIR = Path.home() / '.local' / 'share' / 'tether'
_TETHER_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(_TETHER_DIR / 'tether.log', encoding='utf-8'),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger('tether.daemon')

# ── constants ─────────────────────────────────────────────────────────────────
BUS_NAME        = 'pro.tether.Daemon'
OBJECT_PATH     = '/pro/tether/Daemon'
TETHER_DIR      = _TETHER_DIR
MOUNTS_FILE     = TETHER_DIR / 'mounts.json'
MOUNTPOINT_ROOT = Path('/mnt')

# Compiled once at import time
_LABEL_RE    = re.compile(r'[^a-zA-Z0-9_\-]')
_RSYNC_RE    = re.compile(r'(\d+)%\s+([\d.,]+\w+/s)\s+(\S+)')

# Whitelist of safe rsync flags — anything else is silently ignored
_ALLOWED_RSYNC_OPTS = frozenset({
    '--partial', '--delete', '--perms', '--update',
    '--compress', '--dry-run',
})

# Audit log — append-only record of every state-changing action the
# daemon performs (mountpoint created/removed, credentials written/
# deleted, fstab entry written/removed). This is separate from the
# verbose debug log (tether.log) and exists specifically so that
# cleanup tools (and the user) can verify exactly what Tether created
# on disk and whether it was fully cleaned up — rather than having to
# infer it from current filesystem state alone.
_AUDIT_LOG_PATH = Path.home() / '.local/share/tether/audit.log'


def _audit(action: str, label: str, **details) -> None:
    """
    Append one JSON-line record to the audit log. Never raises —
    a logging failure must not block or fail the underlying operation.
    """
    try:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            'ts':     time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'action': action,
            'label':  label,
            **details,
        }
        with open(_AUDIT_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
    except OSError as e:
        log.warning('Audit log write failed: %s', e)

# Shell metacharacters that must never appear in host or path fields.
# Space is intentionally NOT in this set — SMB share names commonly
# contain spaces (e.g. "Hays Share", "Audio Books"). shlex.quote()
# handles spaces safely wherever these values touch shell commands.
_BLOCKED_INPUT_CHARS = frozenset('\n\r\0|;&$`"\'\\!()')


# ── helpers ───────────────────────────────────────────────────────────────────

def ensure_dirs() -> None:
    TETHER_DIR.mkdir(parents=True, exist_ok=True)
    TETHER_DIR.chmod(0o700)
    if not MOUNTS_FILE.exists():
        MOUNTS_FILE.write_text('{}', encoding='utf-8')


def sanitize_label(label: str) -> str:
    """Return label restricted to [a-zA-Z0-9_-], max 32 chars, never empty."""
    cleaned = _LABEL_RE.sub('_', str(label))[:32].strip('_')
    return cleaned or 'mount'


def validate_user_string(value: str, field: str) -> str | None:
    """
    Return an error string if value contains blocked characters, else None.
    Used for host and remote_path inputs.
    """
    bad = [c for c in value if c in _BLOCKED_INPUT_CHARS]
    if bad:
        return f'ERROR: {field!r} contains disallowed characters: {bad}'
    if not value:
        return f'ERROR: {field!r} must not be empty'
    return None


def resolve_to_ipv4(host: str) -> str:
    """
    Resolve a hostname to its IPv4 address.
    If the host is already an IPv4 address, return it unchanged.
    If only IPv6 is available, log a warning and return the original host.
    DNS resolution times out after 5 seconds to prevent hangs.
    This ensures fstab entries always use IPv4 for maximum compatibility.
    """
    # Already an IPv4 address — return as-is
    try:
        socket.inet_pton(socket.AF_INET, host)
        return host
    except OSError:
        pass

    # Already an IPv6 address — warn and return as-is
    try:
        socket.inet_pton(socket.AF_INET6, host)
        log.warning('Host %r is IPv6 — IPv4 is preferred for CIFS mounts', host)
        return host
    except OSError:
        pass

    # Hostname — resolve with timeout via thread to avoid indefinite hang
    result = [None]
    def _resolve():
        try:
            results = socket.getaddrinfo(host, None, socket.AF_INET)
            if results:
                result[0] = results[0][4][0]
        except socket.gaierror:
            pass

    t = threading.Thread(target=_resolve, daemon=True)
    t.start()
    t.join(timeout=5.0)

    if result[0]:
        log.info('Resolved %r to IPv4 %s', host, result[0])
        return result[0]

    # IPv4 not available — try IPv6 as fallback (also with timeout)
    result6 = [None]
    def _resolve6():
        try:
            results = socket.getaddrinfo(host, None, socket.AF_INET6)
            if results:
                result6[0] = results[0][4][0]
        except socket.gaierror:
            pass

    t6 = threading.Thread(target=_resolve6, daemon=True)
    t6.start()
    t6.join(timeout=5.0)

    if result6[0]:
        log.warning('Could not resolve %r to IPv4, using IPv6 %s', host, result6[0])
        return result6[0]

    # Can't resolve — return original and let mount fail with a clear error
    log.warning('Could not resolve %r — using as-is', host)
    return host


def validate_mountpoint(mountpoint: str) -> bool:
    """
    Ensure mountpoint resolves strictly to /mnt/<name> — no traversal.
    An empty label producing /mnt/ itself is explicitly blocked.
    """
    try:
        p = Path(mountpoint).resolve()
        return p.parent == MOUNTPOINT_ROOT and p.name != ''
    except Exception:
        return False


def write_secure_script(content: str) -> str:
    """
    Write shell script content to a mkstemp path.
    chmod 700 is set BEFORE writing content — no readable window.
    Caller must delete the file after use.
    """
    fd, path = tempfile.mkstemp(suffix='.sh', prefix='tether_')
    try:
        os.chmod(path, 0o700)   # lock down before content lands
        os.write(fd, content.encode('utf-8'))
    finally:
        os.close(fd)
    return path


# ── transfer job ──────────────────────────────────────────────────────────────

class TransferJob:
    def __init__(self, job_id: str, src: str, dst: str) -> None:
        self.job_id     = job_id
        self.src        = src
        self.dst        = dst
        self.progress   = 0
        self.speed      = ''
        self.eta        = ''
        self.status     = 'queued'
        self.extra_opts = []
        self.proc: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None

    def to_dict(self) -> dict:
        return {
            'src': self.src, 'dst': self.dst,
            'progress': self.progress, 'speed': self.speed,
            'eta': self.eta,  'status': self.status,
        }


# ── daemon ────────────────────────────────────────────────────────────────────

class TetherDaemon(dbus.service.Object):

    def __init__(self, bus: dbus.SessionBus, path: str) -> None:
        super().__init__(bus, path)
        self._mounts: dict     = {}
        self._transfers: dict  = {}
        self._job_counter: int = 0
        self._shutdown_flag    = False
        self._main_loop: GLib.MainLoop | None = None
        # Protects _mounts (D-Bus thread + reconnect thread) and _job_counter
        self._lock = threading.Lock()
        self._load_mounts()
        self._start_reconnect_monitor()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load_mounts(self) -> None:
        try:
            data = json.loads(MOUNTS_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                with self._lock:
                    self._mounts = data
        except (json.JSONDecodeError, OSError) as e:
            log.warning('Could not load mounts file: %s', e)
            return
        self._prune_stale_mounts()

    def _has_fstab_entry(self, label: str) -> bool:
        """
        Check whether a live, Tether-tagged fstab line still exists for
        this label. Used to guarantee we never call pkexec for a mount
        that is guaranteed to fail — e.g. a stale mounts.json entry left
        over from before an uninstall/reinstall, where the fstab line
        and credentials file are already gone but the JSON record
        survived (it's treated as personal data and kept on purpose).

        Uses an exact tag comparison (not substring) so a label like
        "Game" can never false-positive match a line tagged "Games".
        """
        target_tag = f'tether:{label}'
        try:
            for line in Path('/etc/fstab').read_text(encoding='utf-8').splitlines():
                if '#' not in line:
                    continue
                comment = line.split('#', 1)[1].strip()
                if comment == target_tag:
                    return True
        except OSError:
            pass
        return False

    def _prune_stale_mounts(self) -> None:
        """
        Remove any mounts.json entries that no longer have a matching
        fstab line. This is the critical safeguard against repeated
        pkexec password prompts for mounts that can never succeed —
        without this, a stale JSON record surviving an uninstall/
        reinstall cycle would cause the reconnect loop to prompt for
        a password every 30 seconds, forever, with no way to succeed.
        """
        with self._lock:
            stale = [
                label for label in self._mounts
                if not self._has_fstab_entry(label)
            ]
            for label in stale:
                log.warning(
                    'Pruning stale mount record %r — no matching fstab '
                    'entry found (likely left over from a previous '
                    'install). It will not be retried.', label
                )
                del self._mounts[label]
            if stale:
                self._save_mounts()

    def _save_mounts(self) -> None:
        """Call while holding self._lock."""
        try:
            MOUNTS_FILE.write_text(
                json.dumps(self._mounts, indent=2), encoding='utf-8'
            )
        except OSError as e:
            log.error('Could not save mounts file: %s', e)

    # ── D-Bus mount methods ───────────────────────────────────────────────────

    @dbus.service.method(BUS_NAME, in_signature='ssssssss', out_signature='s')
    def AddMount(self, label, protocol, host, remote_path, options, cred_label,
                 username, password):
        label       = sanitize_label(str(label))
        protocol    = str(protocol)
        host        = str(host)
        remote_path = str(remote_path)
        options     = str(options)
        cred_label  = str(cred_label)
        username    = str(username)
        password    = str(password)

        if protocol not in ('cifs', 'nfs', 'sshfs'):
            return f'ERROR: Unknown protocol {protocol!r}'

        err = validate_user_string(host, 'host')
        if err:
            return err

        # Resolve hostname to IPv4 for fstab compatibility
        host = resolve_to_ipv4(host)

        # remote_path may contain / but not shell metacharacters
        if any(c in _BLOCKED_INPUT_CHARS - {'/'} for c in remote_path):
            return 'ERROR: remote_path contains disallowed characters'

        mountpoint = str(MOUNTPOINT_ROOT / label)
        if not validate_mountpoint(mountpoint):
            return f'ERROR: Computed mountpoint {mountpoint!r} failed safety check'

        info = {
            'label':       label,
            'protocol':    protocol,
            'host':        host,
            'remote_path': remote_path,
            'options':     options,
            'cred_label':  cred_label,
            'mountpoint':  mountpoint,
            'username':    username,
            'password':    password,
        }
        result = self._do_mount(info)
        if result.startswith('OK'):
            # Strip credentials before persisting — passwords belong in
            # KWallet/credentials store, never in a plaintext JSON file
            safe_info = {k: v for k, v in info.items()
                        if k not in ('username', 'password')}
            with self._lock:
                self._mounts[label] = safe_info
                self._save_mounts()
            cred_path = f'/etc/samba/.tether_{label}' if protocol == 'cifs' else ''
            _audit('add_mount', label,
                   mountpoint=mountpoint, host=host, protocol=protocol,
                   cred_path=cred_path, result='OK')
        else:
            _audit('add_mount', label, host=host, protocol=protocol,
                   result=result)
        return result

    @dbus.service.method(BUS_NAME, in_signature='s', out_signature='s')
    def RemoveMount(self, label):
        label  = sanitize_label(str(label))
        result = self._do_umount(label)
        if result.startswith('OK'):
            with self._lock:
                info = self._mounts.pop(label, None)
                if info is not None:
                    self._save_mounts()
            self._remove_fstab_entry(label)
            # Also remove the CIFS credentials file — this was previously
            # missed, leaving a credentials file on disk after every
            # normal "remove share" operation.
            cred_path = f'/etc/samba/.tether_{label}'
            self._remove_credentials_file(cred_path)
            _audit('remove_mount', label,
                   mountpoint=(info or {}).get('mountpoint', ''),
                   cred_path=cred_path, result='OK')
        else:
            _audit('remove_mount', label, result=result)
        return result

    def _remove_credentials_file(self, cred_path: str) -> None:
        """Delete a CIFS credentials file via pkexec, best-effort."""
        script = '\n'.join([
            '#!/bin/bash',
            'set -uo pipefail',
            f'rm -f {shlex.quote(cred_path)}',
        ]) + '\n'
        path = write_secure_script(script)
        try:
            subprocess.run(
                ['pkexec', 'bash', path],
                capture_output=True, timeout=15
            )
        except Exception as e:
            log.warning('Credentials cleanup failed for %r: %s', cred_path, e)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    @dbus.service.method(BUS_NAME, out_signature='s')
    def ListMounts(self):
        with self._lock:
            snapshot = dict(self._mounts)
        out = {
            label: {**info, 'mounted': self._is_mounted(info['mountpoint'])}
            for label, info in snapshot.items()
        }
        return json.dumps(out)

    # ── orphan recovery ───────────────────────────────────────────────────────
    # Finds mountpoints under /mnt that exist on disk (currently mounted, or
    # left behind in fstab from a previous install) but are not tracked in
    # this daemon's mounts.json. Lets the user clean up leftover state from
    # an earlier Tether install, a manual mount, or interrupted uninstall —
    # without needing to know mount/fstab syntax themselves.

    @dbus.service.method(BUS_NAME, out_signature='s')
    def ScanOrphaned(self):
        with self._lock:
            known = {info['mountpoint'] for info in self._mounts.values()}

        orphans = {}

        # Anything currently mounted under /mnt that we don't track
        try:
            r = subprocess.run(
                ['findmnt', '-rno', 'TARGET,SOURCE,FSTYPE'],
                capture_output=True, text=True, timeout=10
            )
            for line in r.stdout.splitlines():
                parts = line.split(None, 2)
                if len(parts) < 3:
                    continue
                target, source, fstype = parts
                if target.startswith('/mnt/') and target not in known:
                    orphans[target] = {
                        'mountpoint': target, 'source': source,
                        'fstype': fstype, 'mounted': True,
                        'fstab_tagged': False,
                    }
        except Exception as e:
            log.warning('ScanOrphaned: findmnt failed: %s', e)

        # Tether-tagged fstab lines that aren't tracked (may or may not
        # currently be mounted — e.g. leftover from a previous install)
        try:
            for line in Path('/etc/fstab').read_text(encoding='utf-8').splitlines():
                if '# tether:' not in line:
                    continue
                fields = line.split()
                if len(fields) < 3:
                    continue
                target = fields[1]
                if target in known:
                    continue
                if target in orphans:
                    orphans[target]['fstab_tagged'] = True
                else:
                    orphans[target] = {
                        'mountpoint': target, 'source': fields[0],
                        'fstype': fields[2],
                        'mounted': self._is_mounted(target),
                        'fstab_tagged': True,
                    }
        except OSError as e:
            log.warning('ScanOrphaned: could not read fstab: %s', e)

        # Standalone orphaned credential files — e.g. /etc/samba/.tether_X
        # with no active mount and no fstab entry. These can be left behind
        # by interrupted operations, manual cleanup, or (historically) by
        # RemoveMount not deleting the credentials file — fixed in v0.7.7,
        # but this scan still catches any that were created before the fix.
        # Tether always names a mountpoint /mnt/<label> to match its
        # credentials file .tether_<label>, so we can reconstruct the
        # expected mountpoint from the filename alone, even though no
        # directory may exist there anymore.
        try:
            samba_dir = Path('/etc/samba')
            if samba_dir.is_dir():
                fstab_labels = set()
                try:
                    for line in Path('/etc/fstab').read_text(encoding='utf-8').splitlines():
                        if '# tether:' in line:
                            fstab_labels.add(line.rsplit('# tether:', 1)[-1].strip())
                except OSError:
                    pass

                for cred_file in samba_dir.glob('.tether_*'):
                    label = cred_file.name[len('.tether_'):]
                    if not label:
                        continue
                    synthetic_mp = f'/mnt/{label}'
                    if synthetic_mp in known or label in fstab_labels:
                        continue
                    if synthetic_mp in orphans:
                        continue  # already found via findmnt/fstab above
                    orphans[synthetic_mp] = {
                        'mountpoint': synthetic_mp,
                        'source': f'(orphaned credentials file: {cred_file})',
                        'fstype': 'cifs',
                        'mounted': False,
                        'fstab_tagged': False,
                        'credentials_only': True,
                    }
        except OSError as e:
            log.warning('ScanOrphaned: could not scan /etc/samba: %s', e)

        return json.dumps(list(orphans.values()))

    @dbus.service.method(BUS_NAME, in_signature='s', out_signature='s')
    def RemoveOrphanedMounts(self, mountpoints_json):
        """
        Unmount and remove fstab entries/credentials for one or more
        orphaned mountpoints in a SINGLE pkexec call. Batching matters
        because pkexec has no auth caching like sudo — each separate
        pkexec invocation prompts for a password again, so removing
        multiple leftover shares one at a time would mean one password
        prompt per share. This method handles any number of mountpoints
        with exactly one authentication.
        """
        try:
            mountpoints = json.loads(str(mountpoints_json))
        except (json.JSONDecodeError, TypeError, ValueError):
            return 'ERROR: Invalid mountpoint list'

        if not isinstance(mountpoints, list) or not mountpoints:
            return 'ERROR: No mountpoints provided'

        valid = []
        for mp in mountpoints:
            mp = str(mp)
            if not validate_mountpoint(mp):
                log.warning('Skipping unsafe mountpoint in batch removal: %r', mp)
                continue
            valid.append(mp)

        if not valid:
            return 'ERROR: No valid mountpoints after safety check'

        # Filter fstab once, removing lines for ANY of the target mountpoints
        try:
            original = Path('/etc/fstab').read_text(encoding='utf-8')
        except OSError as e:
            return f'ERROR: Could not read /etc/fstab: {e}'

        target_set = set(valid)
        kept       = []
        removed    = 0
        for line in original.splitlines(keepends=True):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                kept.append(line)
                continue
            fields = stripped.split()
            if len(fields) >= 2 and fields[1] in target_set:
                removed += 1
                continue
            kept.append(line)
        new_fstab = ''.join(kept)

        script_lines = [
            '#!/bin/bash',
            'set -uo pipefail',
            'exec 2>&1',
        ]
        for mp in valid:
            label     = sanitize_label(Path(mp).name)
            cred_path = f'/etc/samba/.tether_{label}'
            script_lines += [
                f'echo "Unmounting {mp} (if mounted)"',
                f'umount -- {shlex.quote(mp)} 2>/dev/null || true',
                f'rm -f {shlex.quote(cred_path)} 2>/dev/null || true',
            ]
        script_lines += [
            '',
            'echo "Updating /etc/fstab"',
            'FTMP=$(mktemp)',
            'chmod 600 "$FTMP"',
            f'printf "%s" {shlex.quote(new_fstab)} > "$FTMP"',
            'install -m 644 -o root -g root "$FTMP" /etc/fstab',
            'rm -f "$FTMP"',
            '',
            f'echo "Done — removed {len(valid)} mount(s), '
            f'{removed} fstab line(s)"',
        ]
        script = '\n'.join(script_lines) + '\n'

        path = write_secure_script(script)
        try:
            r = subprocess.run(
                ['pkexec', 'bash', path],
                capture_output=True, text=True, timeout=90
            )
            combined = (r.stdout + r.stderr).strip()
            if r.returncode == 0:
                for mp in valid:
                    self._notify_file_manager_removed(mp)
                return f'OK: Removed {len(valid)} mount(s)'
            return f'ERROR: {combined or "pkexec returned non-zero with no output"}'
        except subprocess.TimeoutExpired:
            return 'ERROR: Operation timed out'
        except Exception as e:
            return f'ERROR: {e}'
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    @dbus.service.method(BUS_NAME, in_signature='s', out_signature='s')
    def RemoveOrphanedMount(self, mountpoint):
        """Single-mount convenience wrapper around RemoveOrphanedMounts."""
        return self.RemoveOrphanedMounts(json.dumps([str(mountpoint)]))

    # ── mount internals ───────────────────────────────────────────────────────

    def _is_mounted(self, mountpoint: str) -> bool:
        try:
            r = subprocess.run(
                ['findmnt', '--noheadings', '--output', 'TARGET', mountpoint],
                capture_output=True, text=True, timeout=10
            )
            return r.returncode == 0 and mountpoint in r.stdout
        except Exception:
            return False

    def _do_mount(self, info: dict) -> str:
        label       = info['label']
        protocol    = info['protocol']
        host        = info['host']
        remote_path = info['remote_path']
        options     = info.get('options', '')
        mountpoint  = info['mountpoint']
        ssh_key     = Path.home() / '.ssh' / 'id_rsa'

        if protocol == 'cifs':
            source    = f'//{host}/{remote_path.lstrip("/")}'
            fs_type   = 'cifs'
            cred_path = f'/etc/samba/.tether_{label}'
            base_opts = f'credentials={cred_path},_netdev,nofail'
        elif protocol == 'nfs':
            source    = f'{host}:{remote_path}'
            fs_type   = 'nfs'
            cred_path = None
            base_opts = '_netdev,nofail'
        elif protocol == 'sshfs':
            source    = f'{host}:{remote_path}'
            fs_type   = 'fuse.sshfs'
            cred_path = None
            base_opts = f'_netdev,nofail,IdentityFile={ssh_key}'
        else:
            return f'ERROR: Unknown protocol {protocol!r}'

        full_opts = f'{base_opts},{options}' if options else base_opts

        # fstab uses spaces as field delimiters — spaces in source or
        # mountpoint paths must be escaped as \040 (octal for space).
        fstab_source     = source.replace(' ', '\\040')
        fstab_mountpoint = mountpoint.replace(' ', '\\040')

        fstab_line = (
            f'{fstab_source} {fstab_mountpoint} {fs_type} {full_opts} 0 0'
            f'  # tether:{label}\n'
        )

        # Load credentials for CIFS so we can write the cred file
        # inside the privileged script — use directly passed credentials
        cred_lines   = []
        cred_content = ''
        if protocol == 'cifs' and cred_path:
            username = info.get('username', '')
            password = info.get('password', '')

            cred_content = f'username={username}\npassword={password}\n'
            cred_lines = [
                '# Step 2: Write CIFS credentials file',
                f'echo "Writing credentials to {cred_path}"',
                f'mkdir -p /etc/samba',
                f'chmod 755 /etc/samba',
                'CTMP=$(mktemp)',
                'chmod 600 "$CTMP"',
                f'printf "%s" {shlex.quote(cred_content)} > "$CTMP"',
                f'install -m 600 -o root -g root "$CTMP" {shlex.quote(cred_path)}',
                'rm -f "$CTMP"',
                f'echo "Credentials file written: {cred_path}"',
            ]

        script = '\n'.join([
            '#!/bin/bash',
            'set -euo pipefail',
            '# Redirect all output to stderr so pkexec captures it',
            'exec 2>&1',
            '',
            '# Step 1: Create mountpoint',
            f'echo "Creating mountpoint {mountpoint}"',
            f'mkdir -p -- {shlex.quote(mountpoint)}',
            f'chmod 755 -- {shlex.quote(mountpoint)}',
            '',
            *cred_lines,
            '',
            '# Step 3: Write fstab entry',
            f'if grep -qF {shlex.quote("tether:" + label)} /etc/fstab; then',
            f'    echo "fstab entry already exists for {label}"',
            'else',
            f'    echo "Writing fstab entry for {label}"',
            f'    printf "%s" {shlex.quote(fstab_line)} >> /etc/fstab',
            'fi',
            '',
            '# Step 4: Mount',
            f'echo "Mounting {mountpoint}"',
            f'mount -- {shlex.quote(mountpoint)}',
            f'echo "Mount successful: {mountpoint}"',
        ]) + '\n'

        log.info('Mount script for %s (credentials redacted):\n%s',
                 label,
                 script.replace(shlex.quote(cred_content), '[CREDENTIALS REDACTED]')
                 if cred_content else script)

        path = write_secure_script(script)
        try:
            r = subprocess.run(
                ['pkexec', 'bash', path],
                capture_output=True, text=True, timeout=120
            )
            combined = (r.stdout + r.stderr).strip()
            log.info('pkexec result for %s: rc=%s output=%s',
                     label, r.returncode, combined)
            if r.returncode == 0:
                return f'OK: Mounted {label} at {mountpoint}'
            return f'ERROR: {combined or "pkexec returned non-zero with no output"}'
        except subprocess.TimeoutExpired:
            return 'ERROR: Mount operation timed out (120s)'
        except Exception as e:
            return f'ERROR: {e}'
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _do_umount(self, label: str) -> str:
        with self._lock:
            info = self._mounts.get(label)
        if not info:
            return f'ERROR: Unknown mount {label!r}'
        mountpoint = info['mountpoint']
        if not validate_mountpoint(mountpoint):
            return f'ERROR: Mountpoint {mountpoint!r} failed safety check'
        try:
            r = subprocess.run(
                ['pkexec', 'umount', '--', mountpoint],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                self._notify_file_manager_removed(mountpoint)
                return f'OK: Unmounted {label}'
            return f'ERROR: {r.stderr.strip()}'
        except subprocess.TimeoutExpired:
            return 'ERROR: Umount timed out'
        except Exception as e:
            return f'ERROR: {e}'

    def _notify_file_manager_removed(self, mountpoint: str) -> None:
        """
        Best-effort: tell Dolphin (and any other KIO-aware file manager)
        that this path is gone, so its Places/sidebar entry updates
        immediately instead of staying stale until a manual refresh or
        reboot. CIFS mounts via fstab don't go through udisks2 like
        removable media does, so Dolphin never hears about the unmount
        on its own.

        This is purely cosmetic — the unmount itself has already
        succeeded by the time this runs. Any failure here (KDE not
        running, signal not supported, etc.) is silently ignored.
        """
        try:
            bus = dbus.SessionBus()
            msg = dbus.lowlevel.SignalMessage(
                '/org/kde/kdirnotify', 'org.kde.KDirNotify', 'FilesRemoved'
            )
            msg.append([f'file://{mountpoint}'], signature='as')
            bus.send_message(msg)
        except Exception as e:
            log.debug('Dolphin refresh notification skipped: %s', e)

    def _remove_fstab_entry(self, label: str) -> None:
        tag    = f'tether:{label}'
        script = '\n'.join([
            '#!/bin/bash',
            'set -euo pipefail',
            'FTMP=$(mktemp)',
            'chmod 600 "$FTMP"',
            f'grep -vF {shlex.quote(tag)} /etc/fstab > "$FTMP" || true',
            'cp "$FTMP" /etc/fstab',
            'rm -f "$FTMP"',
        ]) + '\n'
        path = write_secure_script(script)
        try:
            subprocess.run(
                ['pkexec', 'bash', path],
                capture_output=True, timeout=30
            )
        except Exception as e:
            log.error('fstab cleanup failed for %r: %s', label, e)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    # ── reconnect monitor ─────────────────────────────────────────────────────

    def _start_reconnect_monitor(self) -> None:
        t = threading.Thread(
            target=self._reconnect_loop,
            daemon=True,
            name='tether-reconnect',
        )
        t.start()

    def _is_host_reachable(self, host: str, protocol: str = 'cifs',
                           timeout: float = 3.0) -> bool:
        """
        Quick TCP reachability check — no root required, no password
        prompt. Used to avoid triggering pkexec (and its password dialog)
        when the network is down and the mount would fail anyway.
        """
        port = {'cifs': 445, 'nfs': 2049, 'sshfs': 22}.get(protocol, 445)
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _reconnect_loop(self) -> None:
        # Track consecutive unreachable count per label for backoff —
        # avoids hammering pkexec/network when a share is offline for a
        # long time (e.g. laptop away from home network)
        unreachable_streak: dict[str, int] = {}

        # Track consecutive pkexec/mount failures per label even when the
        # host is reachable and the fstab entry is valid (e.g. stale
        # credentials, share renamed on the server). Without this,
        # any persistent failure would still prompt for a password every
        # 30 seconds forever. next_attempt_at enforces a growing cooldown.
        fail_streak: dict[str, int]      = {}
        next_attempt_at: dict[str, float] = {}

        while not self._shutdown_flag:
            time.sleep(30)
            with self._lock:
                snapshot = dict(self._mounts)

            now = time.monotonic()

            for label, info in snapshot.items():
                mp       = info.get('mountpoint', '')
                host     = info.get('host', '')
                protocol = info.get('protocol', 'cifs')
                if not validate_mountpoint(mp):
                    continue
                if self._is_mounted(mp):
                    unreachable_streak.pop(label, None)
                    fail_streak.pop(label, None)
                    next_attempt_at.pop(label, None)
                    continue

                # Never call pkexec for a mount that has no live fstab
                # entry backing it — guaranteed to fail, and pkexec will
                # still show a password prompt every time regardless.
                # This is the critical safeguard against a stale
                # mounts.json record (e.g. surviving an uninstall that
                # removed the fstab line but not the JSON record)
                # causing endless repeated password prompts.
                if not self._has_fstab_entry(label):
                    log.warning(
                        'Pruning %r during reconnect — fstab entry no '
                        'longer exists. It will not be retried.', label
                    )
                    with self._lock:
                        self._mounts.pop(label, None)
                        self._save_mounts()
                    unreachable_streak.pop(label, None)
                    fail_streak.pop(label, None)
                    next_attempt_at.pop(label, None)
                    continue

                # Check reachability first — never call pkexec for a
                # host we can't even reach. This is what was causing
                # repeated password prompts while offline.
                if host and not self._is_host_reachable(host, protocol):
                    streak = unreachable_streak.get(label, 0) + 1
                    unreachable_streak[label] = streak
                    # Back off: log only occasionally once a pattern
                    # of being offline is established, to avoid log spam
                    if streak <= 3 or streak % 10 == 0:
                        log.info(
                            'Skipping reconnect for %s — host %s '
                            'unreachable (attempt %d)', label, host, streak
                        )
                    continue
                unreachable_streak.pop(label, None)

                # Circuit breaker: if this mount has failed repeatedly
                # even though the host is reachable and fstab is valid,
                # back off with growing delay instead of retrying every
                # cycle. Caps at 10 minutes between attempts.
                if now < next_attempt_at.get(label, 0):
                    continue

                log.info('Reconnecting %s…', label)
                try:
                    r = subprocess.run(
                        ['pkexec', 'mount', '--', mp],
                        capture_output=True, timeout=30
                    )
                    if r.returncode == 0:
                        fail_streak.pop(label, None)
                        next_attempt_at.pop(label, None)
                        log.info('Reconnected %s successfully.', label)
                    else:
                        streak = fail_streak.get(label, 0) + 1
                        fail_streak[label] = streak
                        backoff = min(30 * (2 ** streak), 600)
                        next_attempt_at[label] = now + backoff
                        log.warning(
                            'Reconnect failed for %s (attempt %d) — '
                            'next attempt in %ds. Check that the share '
                            'still exists and credentials are valid.',
                            label, streak, backoff
                        )
                except Exception as e:
                    streak = fail_streak.get(label, 0) + 1
                    fail_streak[label] = streak
                    backoff = min(30 * (2 ** streak), 600)
                    next_attempt_at[label] = now + backoff
                    log.warning('Reconnect failed for %s: %s', label, e)

    # ── transfers ─────────────────────────────────────────────────────────────

    @dbus.service.method(BUS_NAME, in_signature='sss', out_signature='s')
    def StartTransfer(self, src, dst, options_str):
        src         = str(src)
        dst         = str(dst)
        options_str = str(options_str)

        # Validate paths
        for name, val in (('src', src), ('dst', dst)):
            if not (val.startswith('/') or val.startswith('./') or ':' in val):
                return f'ERROR: {name} must be absolute path or host:path'

        # Parse caller-supplied options — whitelist only known safe rsync flags
        extra_opts = [
            opt for opt in options_str.split()
            if opt in _ALLOWED_RSYNC_OPTS
        ]
        ignored = [opt for opt in options_str.split() if opt not in _ALLOWED_RSYNC_OPTS and opt]
        if ignored:
            log.warning('Ignoring unknown transfer options: %r', ignored)

        with self._lock:
            self._job_counter += 1
            job_id = str(self._job_counter)

        job = TransferJob(job_id, src, dst)
        job.extra_opts = extra_opts
        with self._lock:
            self._transfers[job_id] = job

        job.thread = threading.Thread(
            target=self._run_transfer,
            args=(job,),
            daemon=True,
            name=f'tether-xfer-{job_id}',
        )
        job.thread.start()
        return job_id

    def _run_transfer(self, job: TransferJob) -> None:
        job.status = 'running'
        extra_opts = getattr(job, 'extra_opts', [])
        is_dry_run = '--dry-run' in extra_opts

        # Base flags — use --info=progress2 for clean single-line progress
        # Do NOT combine with --progress (they conflict)
        # Dry run: use -v for file listing output instead of progress
        if is_dry_run:
            base_flags = ['rsync', '-avhn']
        else:
            base_flags = ['rsync', '-avh', '--info=progress2']

        cmd = base_flags + extra_opts + ['--', job.src, job.dst]
        log.info('Transfer %s cmd: %s', job.job_id, ' '.join(cmd))

        try:
            job.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
            )
            for line in job.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                if is_dry_run:
                    # For dry runs, log each file that would be transferred
                    log.info('DRY RUN [%s]: %s', job.job_id, line)
                    job.speed = 'Dry run'
                    job.eta   = 'preview only'
                else:
                    self._parse_rsync(job, line)
            try:
                job.proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                log.warning('rsync wait() timed out for job %s; killing',
                            job.job_id)
                job.proc.kill()
                job.proc.wait()
            job.status = 'done' if job.proc.returncode == 0 else 'failed'
            if is_dry_run and job.status == 'done':
                job.speed = 'Dry run complete'
                job.eta   = ''
        except Exception as e:
            log.error('Transfer %s error: %s', job.job_id, e)
            job.status = 'failed'

    def _parse_rsync(self, job: TransferJob, line: str) -> None:
        m = _RSYNC_RE.search(line)
        if m:
            job.progress = int(m.group(1))
            job.speed    = m.group(2)
            job.eta      = m.group(3)
            try:
                self.TransferProgress(
                    job.job_id,
                    dbus.Int32(job.progress),
                    job.speed,
                    job.eta,
                )
            except Exception as e:
                log.debug('Signal emit failed: %s', e)

    @dbus.service.method(BUS_NAME, in_signature='s', out_signature='s')
    def PauseTransfer(self, job_id):
        with self._lock:
            job = self._transfers.get(str(job_id))
        if job and job.proc and job.status == 'running':
            try:
                os.kill(job.proc.pid, signal.SIGSTOP)
                job.status = 'paused'
                return 'OK'
            except ProcessLookupError:
                return 'ERROR: Process already exited'
        return 'ERROR: Job not found or not running'

    @dbus.service.method(BUS_NAME, in_signature='s', out_signature='s')
    def ResumeTransfer(self, job_id):
        with self._lock:
            job = self._transfers.get(str(job_id))
        if job and job.proc and job.status == 'paused':
            try:
                os.kill(job.proc.pid, signal.SIGCONT)
                job.status = 'running'
                return 'OK'
            except ProcessLookupError:
                return 'ERROR: Process already exited'
        return 'ERROR: Job not found or not paused'

    @dbus.service.method(BUS_NAME, in_signature='s', out_signature='s')
    def RemoveTransfer(self, job_id):
        """Remove a completed or failed transfer record from the list."""
        job_id = str(job_id)
        with self._lock:
            job = self._transfers.get(job_id)
            if not job:
                return 'ERROR: Job not found'
            if job.status in ('running', 'paused'):
                return 'ERROR: Cannot remove an active transfer — cancel it first'
            del self._transfers[job_id]
        return 'OK'

    @dbus.service.method(BUS_NAME, in_signature='s', out_signature='s')
    def CancelTransfer(self, job_id):
        """Stop a running or paused transfer and mark it failed."""
        with self._lock:
            job = self._transfers.get(str(job_id))
        if not job:
            return 'ERROR: Job not found'
        if job.proc:
            try:
                job.proc.terminate()
                try:
                    job.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    job.proc.kill()
                    job.proc.wait()
            except ProcessLookupError:
                pass
        job.status = 'failed'
        return 'OK'

    @dbus.service.method(BUS_NAME, out_signature='s')
    def ListTransfers(self):
        with self._lock:
            snap = {jid: job.to_dict() for jid, job in self._transfers.items()}
        return json.dumps(snap)

    @dbus.service.signal(BUS_NAME, signature='siss')
    def TransferProgress(self, job_id, progress, speed, eta):
        """Emitted per rsync progress line. progress is dbus.Int32 percent."""

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def set_main_loop(self, loop: GLib.MainLoop) -> None:
        self._main_loop = loop

    @dbus.service.method(BUS_NAME)
    def Shutdown(self):
        GLib.idle_add(self._do_shutdown)

    def _do_shutdown(self) -> bool:
        self._shutdown_flag = True
        if self._main_loop:
            self._main_loop.quit()
        return False

    def handle_os_signal(self, signum, _frame) -> None:
        log.info('Signal %s received; shutting down', signum)
        GLib.idle_add(self._do_shutdown)


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    ensure_dirs()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus    = dbus.SessionBus()
    _name  = dbus.service.BusName(BUS_NAME, bus)
    daemon = TetherDaemon(bus, OBJECT_PATH)

    loop = GLib.MainLoop()
    daemon.set_main_loop(loop)
    signal.signal(signal.SIGTERM, daemon.handle_os_signal)
    signal.signal(signal.SIGINT,  daemon.handle_os_signal)

    log.info('Tether daemon started on %s', BUS_NAME)
    loop.run()
    log.info('Tether daemon stopped.')
