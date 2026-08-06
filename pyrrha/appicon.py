# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Single source of truth for Pyrrha's application icon.

The icon is bundled in ``pyrrha/icons/`` and loaded directly, so it does not
depend on the installed Pithos theme icon. Used for the window/taskbar icon,
the About box and the notification icon.
"""

import hashlib
import logging
import os
import shutil
import subprocess

from PySide6.QtGui import QIcon

from . import APP_ID

logger = logging.getLogger(__name__)

ICON_PATH = os.path.join(os.path.dirname(__file__), 'icons', 'pyrrha.png')
TRAY_ICON_PATH = os.path.join(os.path.dirname(__file__), 'icons', 'pyrrha-sti.png')


def app_icon():
    return QIcon(ICON_PATH)


def tray_icon():
    return QIcon(TRAY_ICON_PATH)


def _digest(path):
    try:
        with open(path, 'rb') as fh:
            return hashlib.md5(fh.read()).digest()
    except OSError:
        return None


def sync_user_icon():
    """Mirror the bundled app icon into the user's hicolor theme when stale.

    On Wayland the taskbar/window icon is resolved by the compositor from the
    .desktop file's ``Icon=`` name (via the hicolor theme), *not* from
    ``QApplication.setWindowIcon()``. So a new bundled icon does not appear
    until the themed copy under ``$XDG_DATA_HOME/icons`` is refreshed -- which
    is what ``install.sh`` does. Calling this on startup keeps that copy in
    sync automatically, writing only when the content actually differs so
    normal launches touch nothing. Best-effort: never raises.
    """
    try:
        bundled = _digest(ICON_PATH)
        if bundled is None:
            return  # nothing bundled to mirror

        datahome = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
        hicolor = os.path.join(datahome, 'icons', 'hicolor')
        icondir = os.path.join(hicolor, '256x256', 'apps')
        dest = os.path.join(icondir, APP_ID + '.png')

        if _digest(dest) == bundled:
            return  # already up to date

        os.makedirs(icondir, exist_ok=True)
        shutil.copyfile(ICON_PATH, dest)
        logger.info('Refreshed themed app icon at %s', dest)

        # Best-effort cache refresh; harmless (and skipped) if the tool is absent.
        try:
            subprocess.run(
                ['gtk-update-icon-cache', '-qtf', hicolor],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        except OSError:
            pass
    except Exception:
        # Desktop integration is a nicety; never let it break startup.
        logger.debug('sync_user_icon failed', exc_info=True)
