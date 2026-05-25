# Tether — Changelog

## v0.3.0 — Current
**KDE/CachyOS Edition**
- Fixed: Protocol dropdown now shows human-readable names
  - `SMB / CIFS (Windows shares, NAS)` instead of `cifs`
  - `NFS (Linux/Unix shares)` instead of `nfs`
  - `SSHFS (SSH file system)` instead of `sshfs`
- Added: Plain-English hint text under protocol selector explaining when to use each
- Added: Share Name field placeholder text updates dynamically per protocol
- Added: VERSION string in all source files
- CLI wizard now shows friendly protocol names matching the GUI

## v0.2.0
**KDE/CachyOS Edition — First working release**
- Focused version: KDE Plasma on Wayland, CachyOS (Arch-based) only
- D-Bus daemon with mount management, rsync transfer engine, auto-reconnect
- KDE system tray via StatusNotifierItem (Wayland native)
- KWallet credential storage (file fallback)
- Dolphin right-click service menu integration
- KDE autostart on login
- Full CLI: list, add, remove, transfer, pause, resume, cancel, watch
- All security fixes from audit: shlex.quote(), validated mountpoints,
  blocked shell metacharacters, octal chmod, atomic credential writes,
  chmod-before-write on temp scripts
- Confirmed working: daemon, D-Bus handshake, CLI, GUI tray, post-reboot autostart

## v0.1.0
**Multi-distro version — Broad compatibility**
- Supports: KDE, GNOME, XFCE, Cinnamon, MATE, LXQt, Budgie
- Supports: Arch/pacman, Debian/apt, Fedora/dnf
- DE detection via XDG_CURRENT_DESKTOP and process inspection
- Credential backends: KWallet, libsecret, file fallback
- Full security audit: 26 bugs fixed, 10 security findings resolved
- Note: Not live-tested; serves as reference architecture

## v0.4.0
**KDE/CachyOS Edition**
- Fixed: CIFS credentials file (/etc/samba/.tether_<label>) now created
  automatically inside the privileged mount script before mount is attempted.
  Previously the file had to be created manually causing "No such file or
  directory" error on first CIFS mount.
- Credentials are written atomically via mkstemp → install, chmod 600, root:root
- NFS and SSHFS unaffected (no credentials file needed)
- Confirmed working: SMB mount to NAS via 192.168.1.2

## v0.5.0
**KDE/CachyOS Edition**
- Added: Guided four-step wizard as the default add-mount experience
  - Step 1: Auto-discovers servers on local network via nmblookup + avahi
  - Step 2: Lists available shares automatically via smbclient
  - Step 3: Simple Yes/No credentials — no technical terminology
  - Step 4: Name the connection + optional settings via dropdowns/checkboxes
- Added: Advanced Mode toggle in Options menu for power users
  - Persists across sessions via QSettings
  - Advanced dialog retains full technical form with all protocol options
- Added: All optional settings now accessible via GUI (SMB version dropdown,
  read-only checkbox, auto-connect checkbox) — no terminal required
- Added: "Connect to Share" option in tray right-click menu
- Added: Confirmation dialog before disconnecting a share
- Added: "Connecting..." progress indicator during mount operations
- Changed: "Unmount" button renamed to "Disconnect" (more user-friendly)
- Changed: Tab renamed from "Mounts" to "Network Connections"
- Changed: Empty state shows helpful prompt instead of blank space
- Note: Requires nmblookup (part of samba package) for network discovery

## v0.5.1
**KDE/CachyOS Edition**
- Fixed: Wizard Step 2 now handles password-protected servers correctly
  - Tries anonymous share listing first
  - If that fails, shows inline username/password fields without leaving the step
  - Retries share listing with provided credentials
  - Shows clear error if credentials are wrong with option to retry
- Fixed: Credentials entered in Step 2 are automatically carried forward
  to Step 3 so the user is never asked to sign in twice
- Added: Enter key in password field triggers sign-in attempt

## v0.5.2
**KDE/CachyOS Edition**
- Fixed: GUI network discovery and share listing now works correctly
  - Tool paths resolved via shutil.which() + fallback to common Arch locations
  - All subprocess calls now pass an explicitly expanded PATH environment
  - smbclient output parser rewritten to correctly read the Sharename/Type
    table format rather than searching for the word "Disk" in any line
  - FileNotFoundError, TimeoutExpired, and general exceptions now all
    handled individually with clear log messages
  - Debug logging added to smbclient and nmblookup output for diagnostics

## v0.5.3
**KDE/CachyOS Edition**
- Fixed: Share parser now correctly handles share names containing spaces
  (e.g. "Audio Books", "Blue Iris - Storage", "Books and Comics")
- Fixed: Parser finds share name by locating ' Disk' keyword position
  rather than splitting on whitespace — works correctly with TrueNAS,
  Synology, QNAP, and Samba output formats
- Tested against live TrueNAS output with 22 shares including
  multiple names containing spaces

## v0.5.4
**KDE/CachyOS Edition**
- Changed: Wizard Step 2 now asks for credentials upfront rather than
  probing anonymously first — more reliable and works universally
- Changed: Username and password fields clearly marked as optional
  with placeholder text explaining they can be left blank
- Changed: Single "Show Shared Folders" button replaces the two-step
  anonymous probe → credential fallback flow
- Changed: Enter key in password field triggers share listing
- Fixed: Credentials carried forward to Step 3 whether entered here
  or left blank (anonymous access)

## v0.5.5
**KDE/CachyOS Edition**
- Added: Diagnostic output panel in Wizard Step 2
  - Shows raw smbclient stdout, stderr, return code, and parsed shares
  - Visible after every load attempt to aid troubleshooting
  - All output also written to ~/.local/share/tether/tether.log
- Added: Verbose logging of every smbclient invocation including
  full command, return code, stdout, stderr, and parsed result

## v0.5.6
**KDE/CachyOS Edition**
- Fixed: Critical threading bug — WizardPageServer and WizardPageShare
  were using QMetaObject.invokeMethod() with Q_ARG to communicate from
  background threads back to the UI thread. This requires methods to be
  decorated with @pyqtSlot which they were not, causing a silent
  RuntimeError that swallowed all results from smbclient and nmblookup.
  Replaced with proper pyqtSignal on each page class — the correct
  PyQt5 pattern for thread-to-UI communication.
- This was the root cause of share listing never working in the GUI
  despite smbclient working correctly on the command line.

## v0.5.7
**KDE/CachyOS Edition**
- Fixed: Wizard Step 2 layout no longer clips when window is not maximized
  - Share list now uses stretch=1 to fill available vertical space
  - Credential fields fixed at top, share list expands below
  - Manual entry and debug panel anchored at bottom
- Fixed: Debug diagnostic panel now only visible on failure, hidden on success
- Fixed: Folder icon changed from emoji (📁) to text [folder] to avoid
  font rendering issues showing as empty squares on some systems
- Fixed: Wizard minimum size increased to 580x540 to prevent clipping

## v0.5.8
**KDE/CachyOS Edition**
- Fixed: Removed activateWindow() calls that triggered harmless but
  noisy Wayland warning "Wayland does not support QWindow::requestActivate()"
  on every launch. Window show/raise behavior unchanged.

## v0.5.9
**KDE/CachyOS Edition**
- Fixed: CIFS credential file creation now works for every mount, not just
  the first one. Root cause: daemon was calling load_credentials() from
  KWallet AFTER the mount attempt, but credentials weren't saved there yet.
  Fix: credentials now passed directly through D-Bus (AddMount gains two
  new parameters: username and password) and written to the samba cred file
  inside the privileged mount script before mount is called.
- Fixed: AddMount D-Bus signature updated from ssssss to ssssssss
- Fixed: client.py add_mount() updated to pass username and password
- Fixed: frontend _do_mount() passes credentials through to daemon
- Fixed: Wizard title bar truncation — title shortened to "Tether 0.5.9"

## v0.5.10
**KDE/CachyOS Edition**
- Fixed: Mount script now logs each step with echo statements captured
  by pkexec — previously errors were silently swallowed
- Fixed: Both stdout and stderr from pkexec now combined and logged
  so failure reason is always visible in tether.log
- Fixed: Removed unused FTMP variable from fstab section (leftover
  from earlier refactor that was harmless but confusing)
- Fixed: Mount script logs to tether.log via daemon INFO logger
  so every pkexec operation is fully auditable
- Added: exec 2>&1 in mount script to redirect all output through
  pkexec's capture

## v0.5.11
**KDE/CachyOS Edition**
- Fixed: "Connecting..." dialog now closes properly after mount completes
  Root cause: add_mount() D-Bus call blocks the main Qt thread, preventing
  event processing including dialog close. Fix: mount now runs in a
  background thread with pyqtSignal for completion callback — same pattern
  as share listing. Dialog closes cleanly whether mount succeeds or fails.
- Fixed: Duplicate signal connections on repeated mounts prevented by
  disconnecting after each use

## v0.5.12
**KDE/CachyOS Edition**
- Fixed: "Connecting..." dialog now closes reliably after mount completes
  Previous approach used pyqtSignal across threads which failed silently.
  New approach: background thread writes result to a shared dict, QTimer
  polls every 500ms on the main thread until the thread finishes, then
  closes the dialog and shows the result. Guaranteed to run on main thread.

## v0.5.13
**KDE/CachyOS Edition**
- Simplified: Removed "Connecting..." progress dialog entirely.
  The pkexec password prompt already communicates that something
  is happening. No intermediate dialog needed — just mount and
  show success or error when done. Less code, fewer failure modes.

## v0.6.0
**KDE/CachyOS Edition**
- Added: Full GUI transfer interface — no terminal required
  - "New File Transfer..." button in the Transfers tab
  - Browse buttons for source and destination (folder picker)
  - All rsync options as plain-English checkboxes:
    * Resume interrupted transfers (--partial)
    * Skip files already up to date (--update)
    * Compress during transfer (--compress)
    * Preserve file permissions (--perms)
    * Delete files not in source (--delete) — with confirmation warning
    * Dry run — preview without transferring (--dry-run)
  - Delete option shows warning dialog before enabling
- Added: Transfer cards now show plain-English status labels
  (Transferring, Paused, Complete, Failed instead of raw status words)
- Added: Pause/Resume/Cancel buttons correctly enable/disable by status
- Added: rsync option whitelist in daemon — only known safe flags accepted
- Changed: rsync now uses --info=progress2 for cleaner progress output

## v0.6.1
**KDE/CachyOS Edition**
- Fixed: Transfer dialog now shows mounted network shares as selectable
  options in source and destination dropdowns — no path typing needed
- Network shares appear at top of each dropdown labeled with their
  friendly name, host, and share name e.g. "[Network] Games (192.168.1.2/Games)"
- Selecting a share auto-fills the path field with its mountpoint
- "My Computer (browse...)" option opens the local folder picker
- Browse button still available for drilling into subfolders of a share
- Separator line visually separates network shares from local browse option

## v0.6.2
**KDE/CachyOS Edition**
- Fixed: Application crash on dry run transfer
  - --progress and --info=progress2 were being passed together causing
    conflicting rsync output that crashed the progress parser
  - Dry run now uses rsync -avhn (no progress flags) and logs each file
    that would be transferred to tether.log instead
  - Progress parser skipped entirely for dry runs
- Fixed: Dry run completes without attempting any file copies
- Fixed: Transfer card shows "Dry run — previewing files" during dry run
- Fixed: Informational dialog explains where to see dry run results
- Fixed: start_transfer result now checked and error shown if it fails
- Changed: rsync uses --info=progress2 only (removed conflicting --progress)

## v0.6.3
**KDE/CachyOS Edition**
- Fixed: D-Bus signature mismatch on StartTransfer — daemon was running
  with old 'ss' signature after client was updated to pass 3 args ('sss').
  All three files (daemon, client, frontend) must be deployed together
  and daemon restarted for signature changes to take effect.
- Fixed: Qt Wayland warning "does not support QWindow::requestActivate()"
  suppressed via QT_LOGGING_RULES=qt.qpa.wayland=false in both the
  systemd service file and the launcher — purely cosmetic, no functional
  change.

## v0.6.4
**KDE/CachyOS Edition**
- Fixed: Dry run transfer card now shows unambiguous status labels
  - During:  "Dry run — previewing files, nothing is being copied"
  - After:   "Dry run complete — no files were copied"
  - On fail: "Dry run failed"
  - Speed and ETA fields hidden during dry run to avoid confusion
    (3003.22GB/s was misleading — it's just rsync at CPU speed)

## v0.6.5
**KDE/CachyOS Edition**
- Added: Transfer history can now be cleared for privacy
  - "Clear History" button removes all completed/failed transfers
  - Individual ✕ button appears on each card when transfer finishes
  - Active/running transfers are never removed automatically
  - Informational message if no completed transfers to clear

## v0.6.6
**KDE/CachyOS Edition**
- Fixed: Dismissed transfers reappearing after 2 seconds
  Root cause: DaemonPoller was re-adding jobs from the daemon's list
  every poll cycle. Fix: dismissing a card now calls RemoveTransfer
  on the daemon, removing the record at source so the poller never
  sees it again.
- Added: RemoveTransfer D-Bus method on daemon — removes completed
  or failed jobs from the transfer record. Refuses to remove active
  or paused transfers (cancel first).
- Added: remove_transfer() to client proxy

## v0.6.6 (continued)
- Added: update.sh — one-command update script that handles the full
  safe deployment sequence automatically:
  1. Stops tray applet
  2. Stops daemon cleanly + force-kills any lingering process
  3. Copies new .py files to /opt/tether-kde
  4. Updates service file if present
  5. Restarts daemon and verifies it started
  6. Relaunches tray applet
  Usage: ./update.sh (run from the folder containing new files)

## v0.6.6 (continued)
- Added: tether.1 man page — full manual covering all commands, options,
  files, security model, and examples. Installed to /usr/local/share/man/man1/
- Added: README.md — GitHub project page with foreword, feature list,
  architecture overview, installation instructions, and project attribution
- Updated: install.sh now installs the man page automatically

## v0.6.7
**KDE/CachyOS Edition**
- Fixed: Share names containing spaces now mount correctly
  (e.g. "Hays Share", "Audio Books", "Blue Iris - Storage")
  Root cause: space was in _BLOCKED_INPUT_CHARS alongside actual shell
  metacharacters. SMB share names commonly contain spaces and this is
  perfectly valid. shlex.quote() already handles spaces safely in all
  shell contexts — the block was unnecessary and wrong.
  All actual dangerous characters (newline, semicolon, backtick,
  dollar sign, etc.) remain blocked.

## v0.6.7 (continued)
- Fixed: install.sh now copies update.sh and uninstall.sh to
  /opt/tether-kde/ and sets chmod +x on both automatically
- Fixed: update.sh was not executable after manual copy — install.sh
  now handles this correctly so it never needs to be set manually

## v0.6.8
**KDE/CachyOS Edition**
- Fixed: Share names containing spaces now mount correctly end-to-end.
  The fstab entry was being written with literal spaces which the kernel
  fstab parser treats as field delimiters, causing "parse error at line N".
  Fix: spaces in source path and mountpoint are escaped as \040 (the
  standard fstab octal escape for space) before writing to /etc/fstab.
  The kernel fstab parser correctly interprets \040 as a literal space.
  Affects: "Hays Share", "Audio Books", "Blue Iris - Storage", and any
  other SMB share whose name contains spaces.

## v0.6.9
**KDE/CachyOS Edition**
- Added: Automatic IPv4 resolution for all hostnames
  When the user enters a hostname or the wizard discovers a server,
  Tether now resolves it to an IPv4 address before mounting and
  writing the fstab entry. This prevents the system from
  unpredictably choosing IPv6 (which causes fstab compatibility
  issues and inconsistent reconnection behaviour).
  Behaviour:
  - IPv4 address entered → used as-is
  - Hostname entered → resolved to IPv4 via DNS/mDNS
  - IPv6 only available → logged as warning, used as fallback
  - Cannot resolve → original value used, mount will fail clearly

## v0.6.10
**KDE/CachyOS Edition**
- Fixed: Network discovery no longer shows duplicate entries for servers
  that advertise both IPv4 and IPv6 addresses. When both are found,
  only the IPv4 entry is shown. IPv4 is always preferred over IPv6
  for CIFS mount compatibility.

## v0.6.10 (updated)
- Fixed: avahi-browse parser now reads the explicit IPv4/IPv6 protocol
  field (column 3) in avahi's output format rather than trying to detect
  address type. IPv6 entries are skipped at parse time — cleaner and
  more reliable. Tested against real avahi output from TrueNAS showing
  both IPv4 and IPv6 entries for the same server.

## v0.7.0
**KDE/CachyOS Edition**
- SECURITY FIX: Passwords are no longer stored in mounts.json.
  Previously the full info dict including username and password was
  written to ~/.local/share/tether/mounts.json in plaintext. Now
  credentials are stripped before saving — only label, protocol,
  host, remote_path, options, cred_label, and mountpoint are
  persisted. Passwords live only in KWallet or the secure
  credentials store.
- First clean install release — all patches from v0.6.x integrated

## v0.7.1
**KDE/CachyOS Edition**
- Fixed: Network discovery now shows all IPv4 addresses for a server.
  v0.6.10 deduplication was too aggressive — it kept only one entry
  per server name, hiding legitimate secondary IPv4 interfaces.
  New behaviour: IPv6 entries are filtered out, all IPv4 entries kept.
  A NAS with two IPv4 addresses (e.g. 192.168.1.2 and 192.168.1.159)
  now shows both entries so the user can choose the correct one.

## v0.7.2
**KDE/CachyOS Edition**
- Fixed: validate_mountpoint() NameError on fresh install.
  The function body had been accidentally merged into resolve_to_ipv4()
  as unreachable dead code after the return statement, leaving no actual
  validate_mountpoint definition. Fixed by extracting it as a proper
  top-level function between resolve_to_ipv4() and write_secure_script().
