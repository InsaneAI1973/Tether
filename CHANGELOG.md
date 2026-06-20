# Tether — Changelog

## v0.7.3 — Current
**KDE/CachyOS Edition**
- Fixed: Tether now auto-detects X11 vs Wayland and sets QT_QPA_PLATFORM
  automatically. Previously failed to launch on X11 sessions with error:
  "Could not find the Qt platform plugin wayland"
  Now checks WAYLAND_DISPLAY and DISPLAY environment variables and sets
  the correct platform plugin without any manual configuration.
- Added: qt5-wayland and qt6-wayland added to installer dependencies
  so fresh installs on any session type work out of the box.
- Added: make-release.sh — packages all source files into a self-contained
  tarball for GitHub release distribution. No AUR, no cloning required.
  Users download one file, extract, and run ./install.sh
- Fixed: install.sh now embeds all desktop files directly — no longer
  requires tether.desktop or tether-dolphin.desktop to exist in the
  source directory. Fresh clones from GitHub install cleanly.

## v0.7.2
**KDE/CachyOS Edition**
- Fixed: validate_mountpoint() NameError on fresh install.
  The function body had been accidentally merged into resolve_to_ipv4()
  as unreachable dead code. Fixed by extracting it as a proper
  top-level function.

## v0.7.1
**KDE/CachyOS Edition**
- Fixed: Network discovery now shows all IPv4 addresses for a server.
  v0.6.10 deduplication was too aggressive — it kept only one entry
  per server name, hiding legitimate secondary IPv4 interfaces.
  IPv6 entries are filtered out, all IPv4 entries kept.

## v0.7.0
**KDE/CachyOS Edition**
- SECURITY FIX: Passwords are no longer stored in mounts.json.
  Previously the full info dict including username and password was
  written to ~/.local/share/tether/mounts.json in plaintext. Now
  credentials are stripped before saving — only label, protocol,
  host, remote_path, options, cred_label, and mountpoint are
  persisted. Passwords live only in KWallet or the secure
  credentials store.
- First clean install release — all patches from v0.6.x integrated.

## v0.6.10
**KDE/CachyOS Edition**
- Fixed: avahi-browse parser now reads the explicit IPv4/IPv6 protocol
  field (column 3) in avahi output rather than trying to detect address
  type. IPv6 entries are skipped at parse time — cleaner and more
  reliable. Tested against real TrueNAS output.

## v0.6.9
**KDE/CachyOS Edition**
- Added: Automatic IPv4 resolution for all hostnames. Tether now
  resolves hostnames to IPv4 before mounting and writing fstab entries.
  Prevents the system from unpredictably choosing IPv6, which causes
  fstab compatibility issues and inconsistent reconnection behaviour.

## v0.6.8
**KDE/CachyOS Edition**
- Fixed: Share names containing spaces now mount correctly end-to-end.
  Spaces in fstab source and mountpoint paths are now escaped as \040
  (standard fstab octal escape). Affects: "Hays Share", "Audio Books",
  "Blue Iris - Storage", and any SMB share with spaces in the name.

## v0.6.7
**KDE/CachyOS Edition**
- Fixed: Share names containing spaces no longer rejected as "disallowed
  characters". Space was incorrectly in _BLOCKED_INPUT_CHARS — removed.
  shlex.quote() already handles spaces safely in all shell contexts.
- Fixed: install.sh now copies update.sh and uninstall.sh to
  /opt/tether-kde/ with chmod +x set automatically.
- Added: update.sh deployment script handles the full safe stop/copy/
  restart sequence automatically.
- Added: tether.1 man page installed to /usr/local/share/man/man1/
- Added: README.md project page with foreword and attribution.

## v0.6.6
**KDE/CachyOS Edition**
- Fixed: Dismissed transfers no longer reappear after 2 seconds.
  Dismissing a card now calls RemoveTransfer on the daemon, removing
  the record at source so the poller never re-adds it.
- Added: RemoveTransfer D-Bus method — removes completed/failed jobs.
- Added: remove_transfer() to client proxy.

## v0.6.5
**KDE/CachyOS Edition**
- Added: Transfer history privacy controls.
  - "Clear History" button removes all completed/failed transfers.
  - Individual ✕ button on each card when transfer finishes.
  - Active transfers are never removed automatically.

## v0.6.4
**KDE/CachyOS Edition**
- Fixed: Dry run transfer card now shows unambiguous status labels:
  "Dry run — previewing files, nothing is being copied" during run,
  "Dry run complete — no files were copied" when finished.

## v0.6.3
**KDE/CachyOS Edition**
- Fixed: Qt Wayland warning suppressed via QT_LOGGING_RULES.
- Fixed: D-Bus signature mismatch on StartTransfer (ss → sss).

## v0.6.2
**KDE/CachyOS Edition**
- Fixed: Application crash on dry run — conflicting rsync flags
  --progress and --info=progress2 were both being passed.
  Dry run now uses rsync -avhn with no progress flags.

## v0.6.1
**KDE/CachyOS Edition**
- Fixed: Transfer dialog now shows mounted network shares as selectable
  source/destination options. No path typing needed.

## v0.6.0
**KDE/CachyOS Edition**
- Added: Full GUI file transfer interface — no terminal required.
  - "New File Transfer..." button in the Transfers tab.
  - Browse buttons for source and destination (folder picker).
  - All rsync options as plain-English checkboxes:
    Resume, Skip newer, Compress, Preserve permissions,
    Delete (with confirmation warning), Dry run.
- Added: Transfer cards with progress bar, speed, ETA,
  Pause/Resume/Cancel buttons, and plain-English status labels.

## v0.5.x
**KDE/CachyOS Edition**
- v0.5.13: Removed unnecessary "Connecting..." dialog.
- v0.5.12: Mount dialog closes reliably using QTimer polling.
- v0.5.9: Credentials passed directly through D-Bus — no KWallet
  timing dependency. CIFS credential files created for every mount.
- v0.5.6: Critical threading fix — replaced QMetaObject.invokeMethod
  with pyqtSignal for all thread-to-UI communication.
- v0.5.4: Wizard Step 2 asks for credentials upfront — simpler and
  more reliable than anonymous probe + fallback.
- v0.5.3: Share parser handles names with spaces correctly.
- v0.5.0: Guided 4-step wizard, network discovery, share listing,
  Advanced Mode toggle, all options in GUI — no terminal required.

## v0.4.0
**KDE/CachyOS Edition**
- Fixed: CIFS credentials file created automatically before mount.

## v0.3.0
**KDE/CachyOS Edition**
- Fixed: Protocol selector shows human-readable names
  (SMB/CIFS, NFS, SSHFS) instead of raw protocol strings.

## v0.2.0
**KDE/CachyOS Edition — First working release**
- D-Bus daemon, KDE system tray, KWallet credentials, Dolphin
  integration, KDE autostart, full CLI.

## v0.1.0
**Multi-distro reference architecture**
- Supports KDE, GNOME, XFCE, Cinnamon, MATE, LXQt, Budgie.
- Supports pacman, apt, dnf.
- Full security audit: 26 bugs fixed, 10 security findings resolved.
- Not live-tested — serves as reference architecture.

## v0.7.3 (security audit)
**KDE/CachyOS Edition**
- SECURITY: CIFS credentials (username/password) no longer appear in
  tether.log. The mount script is now logged with credentials replaced
  by [CREDENTIALS REDACTED]. Previously the full script including
  plaintext password was written to the log file on every mount.
- SECURITY: Removed circular import — credentials.py no longer imports
  from daemon.py, eliminating a potential import-order vulnerability.
- Fixed: CancelTransfer D-Bus method was missing from the daemon.
  Dead code after return in RemoveTransfer was extracted into a proper
  CancelTransfer method. The Cancel button in the GUI now works correctly.
- Fixed: RemoveMount no longer removes fstab entries and mounts.json
  records when the umount operation fails — data is only cleaned up
  on successful unmount.
- Fixed: DNS resolution in resolve_to_ipv4() now times out after 5
  seconds using a daemon thread, preventing indefinite hangs on
  unreachable nameservers.
- Fixed: socket module moved to module-level import (was inside function).
- Fixed: _ALLOWED_RSYNC_OPTS moved to module-level frozenset constant
  (was recreated as a local set on every StartTransfer call).
- Added: make-release.sh — packages all source files into a self-contained
  tarball for GitHub release distribution. No AUR required.

## v0.7.4
**KDE/CachyOS Edition**
- Fixed: Repeated password prompts while offline. The reconnect monitor
  was calling pkexec mount every 30 seconds for any unmounted share
  regardless of network state — each attempt triggered a password
  dialog even though the mount was guaranteed to fail with no network.
  Fix: a quick TCP reachability check (no root, no password prompt)
  now runs before any pkexec call. Unreachable hosts are skipped
  entirely until they come back online.
- Added: Backoff logging — once a share has been unreachable for a
  few cycles, log messages are throttled to avoid log spam during
  extended offline periods (e.g. laptop away from home network).
- Added: Per-protocol port selection for reachability checks
  (cifs:445, nfs:2049, sshfs:22).

## v0.7.4 (continued — security audit)
- FIXED (functional bug, found in audit): CLI `tether add` command saved
  credentials to KWallet but never passed username/password to the
  daemon's AddMount call. Every password-protected CIFS share added via
  CLI would mount with blank credentials and fail. Now fixed —
  credentials are passed through correctly.
- Added: `--dry-run` flag to `tether transfer` CLI command for feature
  parity with the GUI's dry run checkbox.
- Fixed: uninstall.sh now detects and offers to clean up Tether-managed
  fstab entries and samba credential files. Previously these were left
  behind after uninstall, causing orphaned mount attempts on next boot
  with no Tether daemon present to manage them. A backup of fstab is
  created before any changes (/etc/fstab.tether-uninstall.bak).
- Added: uninstall.sh now removes the installed man page.
- Fixed: update.sh now re-applies the same file ownership and permission
  scheme as install.sh after copying updated files (644 root:root for
  source, 755 for launcher.py). Previously a plain cp could leave
  permissions inconsistent after repeated updates.
- Fixed: tether-daemon.service Documentation= field pointed to a
  placeholder URL (github.com/yourusername/tether) — corrected to the
  real repository.
- Audit: full scan for shell=True, eval/exec, os.system, pickle,
  hardcoded secrets, bare excepts, and unsafe permissions — all clear.

## v0.7.5
**KDE/CachyOS Edition**
- Added: "Scan for Other Mounts" feature — finds mountpoints under /mnt
  that exist (currently mounted, or left in fstab) but aren't tracked by
  the running Tether install. Covers the common case of leftover shares
  from a previous install or an interrupted uninstall that Dolphin can't
  unmount because they're root-owned.
  - GUI: Options menu → "Scan for Other Mounts…" opens a dialog listing
    found mounts with checkboxes; select and click "Unmount & Remove"
    to clean them up (with a confirmation prompt first).
  - CLI: `tether scan` lists found mounts; `tether scan --remove`
    walks through them interactively.
  - Added daemon D-Bus methods: ScanOrphaned, RemoveOrphanedMount.
  - fstab line removal uses exact whitespace-field matching (not
    substring search) so e.g. removing /mnt/Games never affects
    /mnt/Games2 or similar lookalike paths.
  - Associated CIFS credentials file is removed alongside the fstab
    entry and mount.

## v0.7.6
**KDE/CachyOS Edition**
- Fixed: "Scan for Other Mounts" was only reachable via the Options
  menu, which is too easy to miss. Added a visible button directly on
  the Network Connections tab next to "Connect to Network Share…" so
  the feature is discoverable without digging through menus.

## v0.7.7
**KDE/CachyOS Edition**
- Fixed: Removing multiple orphaned mounts via "Scan for Other Mounts"
  triggered a separate pkexec password prompt for EACH mount, since
  pkexec has no authentication caching like sudo. Selecting 2 leftover
  shares meant entering your password twice in a row, which looked
  like Tether was ignoring credentials you'd just entered.
  Fix: added RemoveOrphanedMounts (plural) — batches any number of
  mounts into a single script and a single pkexec call, so removing
  5 leftover shares now takes exactly one authentication, not five.
  Applies to both the GUI dialog and `tether scan --remove`.
- The original single-mount RemoveOrphanedMount D-Bus method is kept
  as a thin wrapper around the batch version for compatibility.

## v0.7.7 — CRITICAL FIX
**KDE/CachyOS Edition**
- CRITICAL: Fixed the root cause of repeated/endless password prompts
  that could lock users out of sudo entirely, requiring a reboot.
  Root cause: mounts.json is intentionally preserved across uninstall/
  reinstall (treated as personal data). If a previous install's fstab
  entries were removed (e.g. during uninstall) but mounts.json still
  listed the labels, the reconnect loop would call pkexec every 30
  seconds for mounts that could never succeed — each call still shows
  a password prompt even though the underlying mount is guaranteed to
  fail. Repeated unanswered/failed authentication attempts in a short
  window can trigger polkit/PAM lockout behaviour on some systems.
  Fix: the daemon now verifies a live, exactly-matching fstab entry
  exists for every mount before ever calling pkexec. Stale records
  with no matching fstab line are automatically pruned from
  mounts.json — both at daemon startup and continuously during the
  reconnect loop — and are never retried again.
- Added: Circuit-breaker backoff for mounts that keep failing even
  with a valid fstab entry and reachable host (e.g. stale stored
  credentials, share renamed on the server). Failures back off
  exponentially (1, 2, 4, 8 minutes, capping at 10 minutes) instead
  of retrying — and prompting — every 30 seconds forever.
- Fixed: fstab tag matching now uses an exact comparison instead of
  substring search, preventing a label like "Game" from falsely
  matching an entry tagged "Games".

## v0.7.7
**KDE/CachyOS Edition**
- FIXED (root cause): `RemoveMount` (used by every normal "remove share"
  action, in both the GUI and CLI) was unmounting the share and removing
  its fstab entry, but never deleting the CIFS credentials file at
  /etc/samba/.tether_LABEL. Every single share removal — going all the
  way back through this project's history — left a leftover credentials
  file behind. The "Scan for Other Mounts" feature was catching the
  symptom; this release fixes the actual source of the leak.
- Added: "Scan for Other Mounts" now also detects standalone orphaned
  credentials files (a leftover .tether_LABEL file with no active mount
  and no fstab entry) — exactly the kind of leftover the RemoveMount bug
  above was creating. These are shown with a clear "leftover password
  file only" label and can be cleaned up the same way as any other
  orphaned mount.
- Added: Audit log. Every AddMount, RemoveMount, and orphan cleanup is
  now recorded to ~/.local/share/tether/audit.log as newline-delimited
  JSON — timestamp, action, label, affected paths, and result. Never
  contains usernames or passwords. View it with the new `tether log`
  command. This gives a durable record of every change Tether has made
  to the system, independent of current filesystem state, so future
  cleanup tooling (or the user) doesn't have to guess what was created.
- Added: `tether log [-n COUNT]` CLI command to view the audit log.

## v0.7.8
**KDE/CachyOS Edition**
- Added: Dolphin sidebar refresh notification after unmounting a share.
  CIFS mounts via fstab don't go through udisks2 like removable media
  does, so Dolphin never receives a live notification when Tether
  unmounts something — the Places/Network entry stayed visible until
  a manual refresh, Dolphin restart, or full reboot. Tether now sends
  a best-effort org.kde.KDirNotify FilesRemoved D-Bus signal after
  every successful unmount (including batch orphan cleanup) so the
  sidebar updates immediately in most cases. This is cosmetic only —
  the actual unmount has already completed successfully regardless of
  whether Dolphin picks up the notification.

## v0.7.9
**KDE/CachyOS Edition**
- Fixed: install.sh's polkit agent detection was using `pgrep -x` with
  guessed process names, which is unreliable since `pgrep -x` matches
  against the kernel's truncated 15-character comm field, not the full
  process name. This caused a false "polkit agent does not appear to
  be running" warning even when pkexec was working correctly. Now
  checks `systemctl --user is-active plasma-polkit-agent.service`
  first (the actual KDE-shipped unit name), falling back to `pgrep -f`
  (full command-line match, not truncated) only if needed.
- Documented: Dolphin Places sidebar may show a removed share until
  Dolphin is restarted or the system reboots — a known KDE/Dolphin
  caching quirk (CIFS-via-fstab mounts don't trigger the same live
  notifications as removable media). Tether already sends a best-
  effort refresh signal; this is now documented as a known limitation
  in the man page rather than something users need to report.
