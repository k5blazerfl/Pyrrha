# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Ported from Pithos' plugins/notification_icon.py (C) 2010-2012 Kevin Mehall.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""System tray icon with playback controls.

Pithos hand-rolled the KDE StatusNotifierItem D-Bus interface plus libdbusmenu.
Qt provides all of that natively through :class:`QSystemTrayIcon` (which speaks
the StatusNotifier protocol under the hood on KDE/Wayland), so this port is much
smaller and uses a plain ``QMenu`` for the context menu.

Features: left-click toggles the window, a context menu with Play/Pause (label
tracks state), Skip, Love, Ban, Tired, Show/Hide and Quit, a tooltip showing the
current track, and — while the tray icon is shown — closing the window hides it
to the tray instead of quitting (register a close interceptor on the window).
The *Configure…* dialog switches between the full-colour and symbolic icons.
"""

import logging

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QLabel, QMenu, QSystemTrayIcon,
    QVBoxLayout,
)

from .. import APP_ID
from ..appicon import app_icon
from ..plugin import PyrrhaPlugin

# (setting value, label). Pyrrha ships a single app icon in the theme.
ICON_CHOICES = [
    (APP_ID, 'App Icon'),
]
DEFAULT_ICON = APP_ID


def _resolve_icon(name):
    # Return a pixmap-based icon (the bundled PNG), not a theme-*name* icon.
    # The tray's StatusNotifierItem then carries the actual Pyrrha bitmap; if we
    # handed it a themed QIcon, Qt would advertise only the icon *name* over
    # D-Bus, which some desktops re-resolve to a stale icon (e.g. a leftover
    # Pithos one from the theme).
    return app_icon()


class NotificationIconPlugin(PyrrhaPlugin):
    preference = 'show_icon'
    description = 'Adds a system tray icon with playback controls'

    def on_prepare(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.prepare_complete(error='No system tray is available.')
            return

        # Reset unknown values (empty, or a stale Pithos icon name carried over
        # by the one-time config migration) to Pyrrha's own icon.
        if self.settings['data'] not in {choice[0] for choice in ICON_CHOICES}:
            self.settings['data'] = DEFAULT_ICON

        self.tray = QSystemTrayIcon(self.window)
        self.tray.setIcon(_resolve_icon(self.settings['data']))
        self.tray.setToolTip('Pyrrha')
        self.tray.activated.connect(self._on_activated)
        self._build_menu()

        self.preferences_dialog = TrayIconPrefsDialog(self.window, self.settings)
        self.settings.changed.connect(self._on_icon_changed)

        # Wiring recorded so we can undo it on disable.
        self._interceptor = None
        self._play_conn = None
        self._song_conn = None
        self.prepare_complete()

    # -- menu --------------------------------------------------------------
    def _build_menu(self):
        menu = QMenu()
        self._playpause_action = menu.addAction(_('Pause'), self.window.playpause)
        menu.addAction(_('Skip'), self.window.next_song)
        menu.addSeparator()
        menu.addAction(_('Love'), lambda: self.window.love_song())
        menu.addAction(_('Ban'), lambda: self.window.ban_song())
        menu.addAction(_('Tired'), lambda: self.window.tired_song())
        menu.addSeparator()
        menu.addAction(_('Show/Hide Pyrrha'), self._toggle_window)
        menu.addAction(_('Quit'), self.window.quit)
        self.menu = menu
        self.tray.setContextMenu(menu)

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._toggle_window()

    def _toggle_window(self, *ignore):
        # Act on the active player view (the skinned shell when in skinned mode).
        if self.window.player_visible():
            self.window.hide_player()
        else:
            self.window.present_player()

    # -- state updates -----------------------------------------------------
    def _play_state_changed(self, playing):
        self._playpause_action.setText(_('Pause') if playing else _('Play'))

    def _song_changed(self, song=None):
        song = song or self.window.current_song
        if song is not None:
            self.tray.setToolTip('{} - {}'.format(song.title, song.artist))

    def _on_icon_changed(self, key):
        if key != 'data':
            return
        self.tray.setIcon(_resolve_icon(self.settings['data']))

    # -- close-to-tray -----------------------------------------------------
    def _close_interceptor(self):
        # Only intercept (hide instead of quit) while the tray icon is shown,
        # so the user is never left without a way to close the app.
        return self.tray.isVisible()

    # -- lifecycle ---------------------------------------------------------
    def on_enable(self):
        self.tray.setVisible(True)
        self._song_changed()
        self._interceptor = self._close_interceptor
        self.window.close_interceptors.append(self._interceptor)
        self._play_conn = self._play_state_changed
        self.window.play_state_changed.connect(self._play_conn)
        self._song_conn = self._song_changed
        self.window.song_changed.connect(self._song_conn)

    def on_disable(self):
        self.tray.setVisible(False)
        if self._interceptor in self.window.close_interceptors:
            self.window.close_interceptors.remove(self._interceptor)
        self._interceptor = None
        for signal_name, slot in (('play_state_changed', self._play_conn),
                                   ('song_changed', self._song_conn)):
            if slot is not None:
                try:
                    getattr(self.window, signal_name).disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self._play_conn = self._song_conn = None
        # If the window was hidden to the tray, make sure it's visible again.
        if not self.window.player_visible():
            self.window.present_player()


class TrayIconPrefsDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(_('Icon Type'))
        self.setModal(True)

        label = QLabel(_('Set the notification icon type'))
        self.combo = QComboBox()
        for value, text in ICON_CHOICES:
            self.combo.addItem(text, value)
        self._reset_combo()

        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        buttons.rejected.connect(self._cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.combo)
        layout.addWidget(buttons)

    def _reset_combo(self):
        idx = self.combo.findData(self.settings['data'])
        if idx >= 0:
            self.combo.setCurrentIndex(idx)

    def _apply(self):
        self.settings['data'] = self.combo.currentData()
        self.hide()

    def _cancel(self):
        self._reset_combo()
        self.hide()
