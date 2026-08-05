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

import os

from PySide6.QtGui import QIcon

ICON_PATH = os.path.join(os.path.dirname(__file__), 'icons', 'pyrrha.png')


def app_icon():
    return QIcon(ICON_PATH)
