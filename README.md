# Tether

**Network Mount Manager for KDE Plasma on Linux**

> *Making Linux feel like home for Windows refugees.*

---

## What is Tether?

Tether is a network file sharing application for KDE Plasma on Linux. It lets
you connect to network shares — Windows shared folders, NAS devices, Linux
file servers — with the same ease as the "Map Network Drive" feature in
Windows. No terminal required. No knowledge of mount commands, fstab, or
network protocols needed.

You open Tether, click through a short wizard, enter your server address and
password, and your network share appears in Dolphin and on your desktop, ready
to use. It reconnects automatically when you log in. It stays connected.

Tether also includes a file transfer engine built on rsync, giving you
resumable transfers with real progress display — something Windows users have
never had natively.

---

## The Purpose

Linux is ready. The hardware support is there. The performance is there. The
software library is growing. What has held back mainstream adoption for decades
is not the kernel or the package manager — it is the small friction points that
Windows handles invisibly, that Linux either does not do at all or buries in a
terminal command.

Tether addresses one of the most common of those friction points: connecting to
a network share. On Windows, you right-click Network, click Map Network Drive,
type a path, and you are done. On Linux, the traditional answer involves
installing cifs-utils, editing /etc/fstab, learning mount syntax, and hoping
the credentials file is in the right place. Most newcomers give up before they
get there.

Tether makes that entire process five clicks and a password.

This project is the first tool in what will become a broader collection aimed
at giving Linux the approachable surface layer it has always deserved. The
underlying technology is excellent. The gap is presentation, not capability.

---

## Features

- **Guided connection wizard** — four steps, plain English, no technical
  knowledge required
- **Automatic network discovery** — finds servers on your local network
  automatically; lists available shares with one click
- **SMB/CIFS, NFS, and SSHFS** — supports Windows shares, NAS devices,
  and Linux file servers
- **Persistent mounts** — shares reconnect automatically at login via fstab
- **KWallet integration** — credentials stored securely in KDE's keyring
- **File transfer engine** — rsync-based with real progress display, speed,
  ETA, pause, resume, and cancel
- **All options in the GUI** — every rsync option (resume, skip newer,
  compress, dry run, delete) available as plain-English checkboxes
- **Advanced Mode** — power users can access the full technical form via
  the Options menu
- **Full CLI** — complete terminal interface for servers and scripting
- **KDE system tray** — lives in your tray, reconnects dropped mounts
  in the background
- **Dolphin integration** — mounts appear in Dolphin's sidebar under Network
- **Scan for Other Mounts** — finds leftover shares from a previous install
  or interrupted uninstall (mount points, fstab entries, or stray credential
  files) and cleans them up in one click — no terminal needed
- **Audit log** — every mount, unmount, and cleanup action is recorded with
  a timestamp; view it with `tether log`

---

## Current Status

> ⚠️ **Beta Software** — Tether is functional and actively tested on real
> hardware but is not yet a stable release. Expect rough edges. Bug reports
> via [GitHub Issues](https://github.com/InsaneAI1973/Tether/issues) are
> very welcome.

**Version 0.7.9 — KDE/CachyOS Edition**

Actively developed and tested on KDE Plasma 6.6.5 / KWin Wayland / CachyOS,
on both laptop and desktop hardware. Core functionality is working:

- ✅ SMB/CIFS mount and unmount via guided wizard and CLI
- ✅ Automatic network discovery — finds servers and lists shares,
  IPv4 only (IPv6 entries filtered automatically)
- ✅ Share names with spaces fully supported
- ✅ Persistent mounts surviving reboot via fstab
- ✅ Reconnects automatically when the network comes back — no repeated
  password prompts while offline
- ✅ KDE system tray with autostart on login
- ✅ Dolphin file manager integration
- ✅ File transfers with progress, speed, ETA, pause/resume/cancel
- ✅ All rsync options as plain-English checkboxes — no terminal needed
- ✅ Transfer history with individual dismiss and Clear History
- ✅ Scan for Other Mounts — finds and cleans up leftover shares,
  fstab entries, and orphaned credential files
- ✅ Audit log of every change Tether makes (`tether log`)
- ✅ Advanced mode for power users
- ✅ Full CLI for headless/server use
- ✅ Credentials stored in KWallet — never in plaintext config files
- ✅ Automatic X11/Wayland detection — no manual environment variables

This release targets **KDE Plasma on CachyOS** (Arch-based). Support for
additional desktop environments and distributions is planned once the core
is stable.

---

## Installation

**Requirements:** CachyOS or Arch Linux, KDE Plasma (Wayland or X11)

### Option 1 — Release package (recommended)

Download the latest release tarball from
[GitHub Releases](https://github.com/InsaneAI1973/Tether/releases), then:

```bash
tar -xzf tether-v0.7.9-kde-cachy.tar.gz
cd tether-v0.7.9-kde-cachy
chmod +x install.sh
./install.sh
```

Or in one line:

```bash
curl -L https://github.com/InsaneAI1973/Tether/releases/latest/download/tether-v0.7.9-kde-cachy.tar.gz | tar -xz && cd tether-v0.7.9-kde-cachy && ./install.sh
```

### Option 2 — Clone from source

```bash
git clone https://github.com/InsaneAI1973/Tether.git
cd Tether/kde-cachy
chmod +x install.sh
./install.sh
```

Both methods use pacman to pull all dependencies automatically — including
`polkit-kde-agent` (password dialogs) and `qt5-wayland`/`qt6-wayland`
(required for the GUI to launch on Wayland sessions). All dependencies come
from official pacman repositories only; the AUR is not used.

**First run test:**

```bash
tether list      # should print "No mounts configured"
tether watch     # live dashboard
```

The Tether icon will appear in your system tray. Right-click any folder in
Dolphin → Actions → Mount Network Location here…

---

## Updating

Download the new release tarball, extract it, and run the included update
script from that folder. It handles the correct stop/copy/restart sequence
automatically — no manual systemctl commands needed:

```bash
tar -xzf tether-vX.Y.Z-kde-cachy.tar.gz
cd tether-vX.Y.Z-kde-cachy
chmod +x update.sh
./update.sh
```

---

## CLI Reference

```
tether list                          List mounts and status
tether add [--label] [--protocol]    Add a network share (interactive)
tether remove LABEL                  Unmount and remove a share
tether scan [--remove]               Find and clean up leftover/orphaned mounts
tether log [-n COUNT]                Show the audit log of changes made
tether transfer SRC DST [--dry-run]  Start an rsync transfer
tether pause JOB_ID                  Pause a transfer
tether resume JOB_ID                 Resume a paused transfer
tether cancel JOB_ID                 Cancel a transfer
tether watch [--interval SECS]       Live dashboard
```

A full man page is included: `man tether`

---

## Architecture

Tether uses a daemon + frontend architecture:

- **daemon.py** — D-Bus service (`pro.tether.Daemon`) owning all privileged
  operations: mounting, fstab management, rsync engine, reconnect monitor
- **frontend.py** — KDE PyQt5 GUI: system tray, management window, wizard
- **cli.py** — Full terminal interface, works over SSH and on servers
- **credentials.py** — Keyring abstraction: KWallet primary, file fallback
- **client.py** — Thin D-Bus proxy used by all frontends

Privileged operations run via `pkexec` helper scripts written to `mkstemp()`
paths with mode 700 before content is written. No `shell=True`. No command
string interpolation. User input validated against a blocklist of shell
metacharacters.

---

## About This Project

Tether was conceived by **David Hays** as part of a broader mission to lower
the barrier to Linux adoption for users coming from Windows. The idea grew from
a simple question: *why does mapping a network drive have to be so much harder
than it is on Windows?*

The entire codebase was produced through **vibe coding** in collaboration with
**Claude** (Anthropic's AI assistant). David provided the vision, the
requirements, and — critically — the real-world testing on actual hardware with
an actual NAS, finding bugs that no amount of static analysis would have caught.
Claude provided the architecture, wrote the code, conducted security audits, and
iterated through each bug fix based on David's test results.

This is what vibe coding looks like when it works: a human with a clear idea of
what they want, and an AI that can build it — working together through the
inevitable messiness of real-world testing until something genuinely useful
emerges.

The goal is for Tether to become the first in a collection of tools that make
Linux feel welcoming to newcomers — not by changing what Linux is, but by
giving it the approachable surface it has always deserved.

---

## Contributing

Contributions are welcome. Please see [CONTRIBUTING.md](CONTRIBUTING.md) for
guidelines.

Bug reports: [GitHub Issues](https://github.com/InsaneAI1973/tether/issues)

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.

Tether is free software. You are free to use, modify, and distribute it under
the terms of the GPL v3.
