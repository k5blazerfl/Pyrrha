# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Application entry point for Pyrrha."""

import argparse
import gettext
import logging
import os
import signal
import sys

# Install a global ``_`` for gettext BEFORE importing any Pyrrha modules, since
# several of them call ``_()`` at import time.
gettext.install('pyrrha')

from PySide6.QtWidgets import QApplication

from . import APP_ID, __version__
from .glib_bridge import GLibBridge


def main():
    parser = argparse.ArgumentParser(prog='pyrrha', description='A Qt Pandora Radio client')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show info messages')
    parser.add_argument('-d', '--debug', action='store_true', help='Show debug messages')
    parser.add_argument('-t', '--test', action='store_true',
                        help='Use a mock service instead of the real Pandora server')
    parser.add_argument('--version', action='store_true', help='Show the version')
    parser.add_argument('--skin', metavar='FILE',
                        help='Use a classic Winamp (.wsz) skinned UI (prototype)')
    parser.add_argument('--scale', type=float, default=1.0,
                        help='Initial skinned-UI scale factor (e.g. 1, 1.5, 2)')
    args = parser.parse_args()

    if args.version:
        print('Pyrrha {}'.format(__version__))
        return 0

    if args.debug:
        log_level = logging.DEBUG
    elif args.verbose:
        log_level = logging.INFO
    else:
        log_level = logging.WARN
    logging.basicConfig(
        level=log_level,
        format='%(levelname)s - %(module)s:%(funcName)s:%(lineno)d - %(message)s',
    )

    # PulseAudio stream metadata.
    os.environ.setdefault('PULSE_PROP_application.name', 'Pyrrha')
    os.environ.setdefault('PULSE_PROP_application.id', APP_ID)
    os.environ.setdefault('PULSE_PROP_media.role', 'music')

    app = QApplication(sys.argv)
    app.setOrganizationName(APP_ID)
    app.setApplicationName('Pyrrha')
    app.setApplicationDisplayName('Pyrrha')
    app.setDesktopFileName(APP_ID)
    from .appicon import app_icon, sync_user_icon
    app.setWindowIcon(app_icon())
    # Keep the compositor-visible themed icon in step with the bundled one
    # (Wayland ignores setWindowIcon for the taskbar). No-op when unchanged.
    sync_user_icon()

    # Flush the QSettings-backed config to disk on exit (writes are otherwise
    # only synced periodically by Qt).
    from .settings import get_settings
    app.aboutToQuit.connect(get_settings().sync)

    # Let Ctrl+C terminate the app from the terminal.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # One-time import of an existing Pithos configuration (non-destructive).
    from .migrate import maybe_migrate_from_pithos
    maybe_migrate_from_pithos()

    # Drive the GLib main context so GStreamer, libsecret and the worker keep
    # functioning under Qt's event loop.
    bridge = GLibBridge()
    bridge.start()

    # Import the window only after the gettext ``_`` is set up.
    from .window import PyrrhaWindow
    window = PyrrhaWindow(app, test_mode=args.test)

    if args.skin:
        # The native window becomes the (hidden) controller; the skinned window
        # is the visible face over it.
        from .skinned.skin import Skin
        from .skinned.window import SkinnedShell
        skin_path = args.skin
        if not os.path.exists(skin_path):
            # Resolve a bare name (e.g. --skin Glare) to a bundled skin.
            bundled = os.path.join(os.path.dirname(__file__), 'skins', args.skin)
            if os.path.isdir(bundled):
                skin_path = bundled
        skinned = SkinnedShell(window, Skin(skin_path), scale=args.scale)
        window.set_skinned_shell(skinned)   # enables the view toggle in both menus
        skinned.show()
        window.settings['skinned-view'] = True   # remember for next start
    elif window.settings['skinned-view']:
        # Restore the skinned view from the last session, honoring the saved
        # classic/modern skin mode. Fall back to the standard window if the
        # skinned shell can't be built (e.g. no skins available).
        if not window.show_skinned_view(force_modern=False):
            window.show()
    else:
        window.show()

    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
