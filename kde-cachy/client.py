#!/usr/bin/env python3
"""
Tether — KDE/CachyOS Edition
D-Bus Client Proxy

Auto-starts the daemon if not running.
One module-level bus and proxy per process — no redundant connections.
"""

VERSION = '0.7.0'

import os
import sys
import json
import time
import subprocess
import logging
from pathlib import Path

log = logging.getLogger('tether.client')

BUS_NAME      = 'pro.tether.Daemon'
OBJECT_PATH   = '/pro/tether/Daemon'
DAEMON_SCRIPT = Path(__file__).parent / 'daemon.py'

_bus   = None
_proxy = None


def _get_bus():
    global _bus
    if _bus is None:
        import dbus
        _bus = dbus.SessionBus()
    return _bus


def _start_daemon() -> None:
    subprocess.Popen(
        [sys.executable, str(DAEMON_SCRIPT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def get_proxy(timeout: float = 15.0):
    global _proxy
    if _proxy is not None:
        return _proxy

    import dbus
    bus             = _get_bus()
    delay           = 0.1
    elapsed         = 0.0
    daemon_launched = False

    while elapsed < timeout:
        try:
            obj    = bus.get_object(BUS_NAME, OBJECT_PATH)
            _proxy = dbus.Interface(obj, dbus_interface=BUS_NAME)
            return _proxy
        except dbus.DBusException:
            if not daemon_launched:
                log.info('Starting Tether daemon…')
                _start_daemon()
                daemon_launched = True
            time.sleep(delay)
            elapsed += delay
            delay    = min(delay * 2, 5.0)

    raise RuntimeError(
        f'Tether daemon did not respond within {timeout:.0f}s.\n'
        f'Check log: {Path.home()}/.local/share/tether/tether.log'
    )


def _parse(raw, context: str) -> dict:
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        log.error('%s parse error: %s', context, e)
        return {}


class TetherClient:

    def __init__(self) -> None:
        self._proxy = get_proxy()
        self._bus   = _get_bus()

    # mounts
    def add_mount(self, label, protocol, host, remote_path,
                  options='', cred_label='',
                  username='', password='') -> str:
        return str(self._proxy.AddMount(
            label, protocol, host, remote_path,
            options, cred_label, username, password
        ))

    def remove_mount(self, label: str) -> str:
        return str(self._proxy.RemoveMount(label))

    def list_mounts(self) -> dict:
        return _parse(self._proxy.ListMounts(), 'list_mounts')

    # transfers
    def start_transfer(self, src: str, dst: str,
                       options: list = None) -> str:
        opts_str = ' '.join(options) if options else ''
        return str(self._proxy.StartTransfer(src, dst, opts_str))

    def pause_transfer(self, job_id: str) -> str:
        return str(self._proxy.PauseTransfer(str(job_id)))

    def resume_transfer(self, job_id: str) -> str:
        return str(self._proxy.ResumeTransfer(str(job_id)))

    def remove_transfer(self, job_id: str) -> str:
        return str(self._proxy.RemoveTransfer(str(job_id)))

    def cancel_transfer(self, job_id: str) -> str:
        return str(self._proxy.CancelTransfer(str(job_id)))

    def list_transfers(self) -> dict:
        return _parse(self._proxy.ListTransfers(), 'list_transfers')

    def shutdown_daemon(self) -> None:
        self._proxy.Shutdown()

    def connect_signal(self, signal_name: str, handler) -> None:
        self._bus.add_signal_receiver(
            handler,
            dbus_interface=BUS_NAME,
            signal_name=signal_name,
        )
