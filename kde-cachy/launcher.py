#!/usr/bin/env python3
"""
Tether — KDE/CachyOS Edition
Launcher

Simple entry point — no DE detection needed.
Adds the kde-cachy directory to sys.path so all local imports work,
then starts either the GUI (default) or CLI based on arguments.
"""

VERSION = '0.7.0'

import os
import sys
from pathlib import Path

# Ensure imports resolve from this directory
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Verify we are actually on a KDE Plasma session before starting GUI
def _check_kde() -> bool:
    de = (
        os.environ.get('XDG_CURRENT_DESKTOP', '') + ' ' +
        os.environ.get('DESKTOP_SESSION', '')
    ).lower()
    return 'kde' in de or 'plasma' in de


def main():
    # Suppress Qt Wayland warning about requestActivate — cosmetic only,
    # not a functional issue
    import os
    os.environ.setdefault('QT_LOGGING_RULES', 'qt.qpa.wayland=false')
    # CLI commands pass through directly — no DE check needed
    cli_commands = {'list', 'add', 'remove', 'transfer',
                    'pause', 'resume', 'cancel', 'watch'}

    if len(sys.argv) > 1 and sys.argv[1] in cli_commands:
        from cli import run
        run()
        return

    # GUI — verify KDE is running
    if not _check_kde():
        print(
            'ERROR: Tether KDE edition requires KDE Plasma.\n'
            'XDG_CURRENT_DESKTOP is not set to KDE/Plasma.\n'
            'For CLI use: tether list / add / watch / …',
            file=sys.stderr
        )
        sys.exit(1)

    from frontend import run
    run()


if __name__ == '__main__':
    main()
