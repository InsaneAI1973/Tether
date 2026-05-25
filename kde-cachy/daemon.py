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

VERSION = '0.7.2'

import re
import os
import sys
import json
import shlex
import signal
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
    This ensures fstab entries always use IPv4 for maximum compatibility.
    """
    import socket
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

    # Hostname — resolve preferring IPv4
    try:
        results = socket.getaddrinfo(host, None, socket.AF_INET)
        if results:
            ipv4 = results[0][4][0]
            log.info('Resolved %r to IPv4 %s', host, ipv4)
            return ipv4
    except socket.gaierror:
        pass

    # IPv4 not available — try IPv6 as fallback
    try:
        results = socket.getaddrinfo(host, None, socket.AF_INET6)
        if results:
            ipv6 = results[0][4][0]
            log.warning('Could not resolve %r to IPv4, using IPv6 %s', host, ipv6)
            return ipv6
    except socket.gaierror:
        pass

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
        return result

    @dbus.service.method(BUS_NAME, in_signature='s', out_signature='s')
    def RemoveMount(self, label):
        label = sanitize_label(str(label))
        result = self._do_umount(label)
        with self._lock:
            if label in self._mounts:
                del self._mounts[label]
                self._save_mounts()
        self._remove_fstab_entry(label)
        return result

    @dbus.service.method(BUS_NAME, out_signature='s')
    def ListMounts(self):
        with self._lock:
            snapshot = dict(self._mounts)
        out = {
            label: {**info, 'mounted': self._is_mounted(info['mountpoint'])}
            for label, info in snapshot.items()
        }
        return json.dumps(out)

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
        cred_lines = []
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

        log.info('Mount script for %s:\n%s', label, script)

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
                return f'OK: Unmounted {label}'
            return f'ERROR: {r.stderr.strip()}'
        except subprocess.TimeoutExpired:
            return 'ERROR: Umount timed out'
        except Exception as e:
            return f'ERROR: {e}'

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

    def _reconnect_loop(self) -> None:
        while not self._shutdown_flag:
            time.sleep(30)
            with self._lock:
                snapshot = dict(self._mounts)
            for label, info in snapshot.items():
                mp = info.get('mountpoint', '')
                if not validate_mountpoint(mp):
                    continue
                if not self._is_mounted(mp):
                    log.info('Reconnecting %s…', label)
                    try:
                        subprocess.run(
                            ['pkexec', 'mount', '--', mp],
                            capture_output=True, timeout=30
                        )
                    except Exception as e:
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
        _ALLOWED_OPTS = {
            '--partial', '--delete', '--perms', '--update',
            '--compress', '--dry-run',
        }
        extra_opts = []
        for opt in options_str.split():
            if opt in _ALLOWED_OPTS:
                extra_opts.append(opt)
            else:
                log.warning('Ignoring unknown transfer option: %r', opt)

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
        """Remove a completed or failed transfer from the record."""
        job_id = str(job_id)
        with self._lock:
            job = self._transfers.get(job_id)
            if not job:
                return 'ERROR: Job not found'
            if job.status in ('running', 'paused'):
                return 'ERROR: Cannot remove an active transfer — cancel it first'
            del self._transfers[job_id]
        return 'OK'
        with self._lock:
            job = self._transfers.get(str(job_id))
        if job and job.proc:
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
        return 'ERROR: Job not found'

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
