#!/usr/bin/env python3
"""
Tether — KDE/CachyOS Edition
CLI Frontend

Full terminal interface — works headless, over SSH, in scripts.
"""

VERSION = '0.7.9'

import sys
import os
import time
import json
import argparse
import getpass
import logging
from pathlib import Path

log = logging.getLogger('tether.cli')

# ── terminal detection ────────────────────────────────────────────────────────

_TTY  = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
_UTF8 = _TTY and (getattr(sys.stdout, 'encoding', '') or '').lower().replace('-','') in ('utf8','utf-8')

RESET  = '\033[0m'    if _TTY else ''
BOLD   = '\033[1m'    if _TTY else ''
GREEN  = '\033[32m'   if _TTY else ''
RED    = '\033[31m'   if _TTY else ''
YELLOW = '\033[33m'   if _TTY else ''
CYAN   = '\033[36m'   if _TTY else ''
CLEAR  = '\033[2J\033[H' if _TTY else ''


def _bar(pct: int, width: int = 30) -> str:
    n = max(0, min(width, int(width * pct / 100)))
    if _UTF8:
        return f'[{GREEN}{"█"*n}{RESET}{"░"*(width-n)}]'
    return f'[{"#"*n}{"-"*(width-n)}]'


def _client():
    from client import TetherClient
    try:
        return TetherClient()
    except RuntimeError as e:
        print(f'{RED}ERROR:{RESET} {e}', file=sys.stderr)
        sys.exit(1)


def _ask(prompt: str, required: bool = True) -> str:
    while True:
        val = input(f'{prompt}: ').strip()
        if val or not required:
            return val
        print('  (required)')


def _choose(prompt: str, options: list) -> str:
    for i, o in enumerate(options, 1):
        print(f'  {i}) {o}')
    while True:
        c = input(f'{prompt} [1-{len(options)}]: ').strip()
        if c.isdigit() and 1 <= int(c) <= len(options):
            return options[int(c)-1]
        print('  Invalid.')


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_list(args):
    mounts = _client().list_mounts()
    if not mounts:
        print('No mounts configured.')
        return
    print(f'\n{BOLD}Network Mounts:{RESET}')
    for label, info in mounts.items():
        dot = f'{GREEN}●{RESET}' if info.get('mounted') else f'{RED}●{RESET}'
        print(f'  {dot}  {BOLD}{label}{RESET}')
        print(f'       {CYAN}{info["protocol"]}://{info["host"]}'
              f'/{info["remote_path"]}{RESET}')
        print(f'       mountpoint: {info["mountpoint"]}')
    print()


def cmd_add(args):
    client   = _client()
    label    = getattr(args, 'label', '')    or _ask('Label (e.g. my-nas)')
    _proto_display = [
        'SMB/CIFS  (Windows shares, NAS)',
        'NFS  (Linux/Unix shares)',
        'SSHFS  (SSH file system)',
    ]
    _proto_internal = ['cifs', 'nfs', 'sshfs']
    if getattr(args, 'protocol', ''):
        protocol = args.protocol
    else:
        idx      = _choose('Protocol', _proto_display)
        protocol = _proto_internal[_proto_display.index(idx)]
    host     = getattr(args, 'host', '')     or _ask('Host (IP or hostname)')
    path     = getattr(args, 'path', '')     or _ask('Remote path')
    options  = getattr(args, 'options', '')  or _ask('Extra options', required=False)

    username = password = ''
    if protocol in ('cifs', 'sshfs'):
        username = _ask('Username (blank to skip)', required=False)
        if username:
            password = getpass.getpass('Password: ')

    cred_saved = False
    if username:
        try:
            from credentials import save_credentials
            save_credentials(label, username, password)
            cred_saved = True
            print(f'{GREEN}Credentials saved to KWallet.{RESET}')
        except Exception as e:
            print(f'{YELLOW}Warning: KWallet save failed: {e}{RESET}')

    print(f'Mounting {CYAN}{label}{RESET}…', end=' ', flush=True)
    result = client.add_mount(
        label, protocol, host, path, options, label,
        username, password,
    )

    if result.startswith('OK'):
        print(f'{GREEN}Done.{RESET}')
    else:
        print(f'{RED}Failed.{RESET}')
        print(f'  {result}')
        if cred_saved:
            try:
                from credentials import delete_credentials
                delete_credentials(label)
            except Exception:
                pass


def cmd_remove(args):
    client = _client()
    label  = getattr(args, 'label', '') or _ask('Label to remove')
    print(f'Unmounting {CYAN}{label}{RESET}…', end=' ', flush=True)
    result = client.remove_mount(label)
    if result.startswith('OK'):
        print(f'{GREEN}Done.{RESET}')
    else:
        print(f'{RED}Failed:{RESET} {result}')


def cmd_scan(args):
    client  = _client()
    orphans = client.scan_orphaned_mounts()

    if not orphans:
        print(f'{GREEN}No other mounts found.{RESET} '
              f'Everything under /mnt is managed by Tether.')
        return

    print(f'\n{BOLD}Found {len(orphans)} mount(s) not managed by Tether:{RESET}\n')
    for i, o in enumerate(orphans, 1):
        status = []
        if o.get('credentials_only'):
            status.append('leftover password file only — no mount, no fstab entry')
        else:
            status.append('mounted' if o.get('mounted') else 'not mounted')
            if o.get('fstab_tagged'):
                status.append('fstab entry present')
        print(f'  {i}) {CYAN}{o["mountpoint"]}{RESET}')
        print(f'     {o.get("source","?")}  ({o.get("fstype","?")})  '
              f'— {", ".join(status)}')
    print()

    if not getattr(args, 'remove', False):
        print(f'Run {BOLD}tether scan --remove{RESET} to unmount and '
              f'clean these up interactively.')
        return

    to_remove = []
    for o in orphans:
        mp = o['mountpoint']
        reply = input(f'Remove {CYAN}{mp}{RESET}? [y/N] ').strip().lower()
        if reply == 'y':
            to_remove.append(mp)
        else:
            print('  Skipped.')

    if not to_remove:
        print('Nothing selected.')
        return

    print(f'\nRemoving {len(to_remove)} mount(s) — '
          f'one authentication prompt for all of them…')
    result = client.remove_orphaned_mounts(to_remove)
    if result.startswith('OK'):
        print(f'{GREEN}{result}{RESET}')
    else:
        print(f'{RED}Failed:{RESET} {result}')


def cmd_transfer(args):
    client  = _client()
    src     = getattr(args, 'src', '') or _ask('Source path')
    dst     = getattr(args, 'dst', '') or _ask('Destination path')
    options = ['--dry-run'] if getattr(args, 'dry_run', False) else None
    result  = client.start_transfer(src, dst, options)
    if result.startswith('ERROR'):
        print(f'{RED}Failed:{RESET} {result}')
    else:
        print(f'Transfer started (job {CYAN}{result}{RESET}).')
        print(f'Monitor with: {BOLD}tether watch{RESET}')


def cmd_pause(args):
    print(_client().pause_transfer(args.job_id))

def cmd_resume(args):
    print(_client().resume_transfer(args.job_id))

def cmd_cancel(args):
    print(_client().cancel_transfer(args.job_id))


def cmd_watch(args):
    client   = _client()
    interval = getattr(args, 'interval', 2)

    try:
        while True:
            mounts    = client.list_mounts()
            transfers = client.list_transfers()

            lines = [
                f'{BOLD}╔══════════════════════════════╗{RESET}',
                f'{BOLD}║    Tether  –  Live View      ║{RESET}',
                f'{BOLD}╚══════════════════════════════╝{RESET}',
                '',
                f'{BOLD}Mounts:{RESET}',
            ]

            if not mounts:
                lines.append('  (none)')
            else:
                for label, info in mounts.items():
                    dot = f'{GREEN}●{RESET}' if info.get('mounted') else f'{RED}●{RESET}'
                    lines.append(
                        f'  {dot}  {label:20s}  '
                        f'{info["protocol"]}://{info["host"]}/{info["remote_path"]}'
                    )

            lines += ['', f'{BOLD}Transfers:{RESET}']
            if not transfers:
                lines.append('  (none)')
            else:
                for jid, job in transfers.items():
                    pct = job.get('progress', 0)
                    st  = job.get('status', '')
                    c   = GREEN if st=='done' else (RED if st=='failed' else YELLOW)
                    lines.append(
                        f'  [{jid}] {c}{st:8s}{RESET} {_bar(pct)} '
                        f'{pct:3d}%  {job.get("speed",""):12s}  '
                        f'ETA {job.get("eta","")}'
                    )
                    lines.append(
                        f'        {job.get("src","?")} → {job.get("dst","?")}'
                    )

            lines.append(
                f'\n  {YELLOW}Ctrl+C to exit{RESET}  '
                f'({time.strftime("%H:%M:%S")})'
            )

            if _TTY:
                sys.stdout.write(CLEAR + '\n'.join(lines))
                sys.stdout.flush()
            else:
                print('\n'.join(lines) + '\n---')

            time.sleep(interval)

    except KeyboardInterrupt:
        if _TTY:
            print()


# ── parser ────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='tether',
        description='Tether – Network Mount Manager (KDE/CachyOS)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  tether add --label nas --protocol cifs --host 192.168.1.10 --path share\n'
            '  tether list\n'
            '  tether watch\n'
            '  tether transfer /mnt/nas/movie.mkv /home/user/Videos/\n'
        ),
    )
    sub = p.add_subparsers(dest='command', metavar='COMMAND')

    sub.add_parser('list', help='List mounts and connection status')

    a = sub.add_parser('add', help='Mount a network share')
    a.add_argument('--label',    default='')
    a.add_argument('--protocol', default='', choices=['cifs','nfs','sshfs'])
    a.add_argument('--host',     default='')
    a.add_argument('--path',     default='')
    a.add_argument('--options',  default='')

    r = sub.add_parser('remove', help='Unmount and remove a share')
    r.add_argument('label', nargs='?', default='')

    sc = sub.add_parser('scan', help='Find mounts under /mnt not managed by Tether')
    sc.add_argument('--remove', action='store_true',
                     help='Interactively unmount and remove found mounts')

    t = sub.add_parser('transfer', help='Start rsync transfer with resume support')
    t.add_argument('src', nargs='?', default='')
    t.add_argument('dst', nargs='?', default='')
    t.add_argument('--dry-run', action='store_true',
                    help='Preview what would be transferred without copying')

    pa = sub.add_parser('pause',  help='Pause a transfer')
    pa.add_argument('job_id')

    re = sub.add_parser('resume', help='Resume a paused transfer')
    re.add_argument('job_id')

    ca = sub.add_parser('cancel', help='Cancel a transfer')
    ca.add_argument('job_id')

    w = sub.add_parser('watch', help='Live dashboard')
    w.add_argument('--interval', type=int, default=2, metavar='SECS')

    lg = sub.add_parser('log', help='Show the audit log of mount/credential changes')
    lg.add_argument('-n', type=int, default=20, metavar='COUNT',
                     help='Number of most recent entries to show (default: 20)')

    return p


def cmd_log(args):
    path = Path.home() / '.local/share/tether/audit.log'
    if not path.exists():
        print('No audit log yet — no changes have been recorded.')
        return

    lines = path.read_text(encoding='utf-8').splitlines()
    n     = max(1, getattr(args, 'n', 20))
    for line in lines[-n:]:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts     = entry.pop('ts', '?')
        action = entry.pop('action', '?')
        label  = entry.pop('label', '?')
        result = entry.pop('result', '?')
        color  = GREEN if result == 'OK' else (RED if result.startswith('ERROR') else YELLOW)
        extras = '  '.join(f'{k}={v}' for k, v in entry.items() if v)
        print(f'{ts}  {BOLD}{action:14s}{RESET}  {CYAN}{label}{RESET}  '
              f'{color}{result}{RESET}  {extras}')


COMMANDS = {
    'list': cmd_list, 'add': cmd_add, 'remove': cmd_remove,
    'scan': cmd_scan, 'log': cmd_log,
    'transfer': cmd_transfer, 'pause': cmd_pause,
    'resume': cmd_resume, 'cancel': cmd_cancel, 'watch': cmd_watch,
}


def run():
    parser = build_parser()
    args   = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    fn = COMMANDS.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    run()
