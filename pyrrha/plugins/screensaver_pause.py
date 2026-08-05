# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Ported from Pithos' plugins/screensaver_pause.py (C) 2010-2012 Kevin Mehall.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Pause playback while the screensaver is active, resume afterwards.

Pithos read ``GtkApplication``'s ``screensaver-active`` property (GTK 3.24+),
which Pyrrha has no equivalent for. Instead this subscribes to the screensaver's
``ActiveChanged(bool)`` D-Bus signal via the session bus (dispatched through the
pumped GLib context). It watches both the freedesktop and GNOME variants so it
works across desktops (KDE emits ``org.freedesktop.ScreenSaver``).
"""

import logging

from gi.repository import Gio

from ..plugin import PyrrhaPlugin

# (interface, object path) pairs that expose ActiveChanged.
SCREENSAVERS = [
    ('org.freedesktop.ScreenSaver', '/org/freedesktop/ScreenSaver'),
    ('org.gnome.ScreenSaver', '/org/gnome/ScreenSaver'),
]


class ScreenSaverPausePlugin(PyrrhaPlugin):
    preference = 'enable_screensaverpause'
    description = 'Pause playback when the screen locks'

    def on_prepare(self):
        if self.bus is None:
            self.prepare_complete(error='Failed to connect to DBus')
            return
        self._subs = []
        self._wasplaying = False
        self.prepare_complete()

    def on_enable(self):
        for interface, path in SCREENSAVERS:
            sub = self.bus.signal_subscribe(
                None,            # any sender
                interface,
                'ActiveChanged',
                path,
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_active_changed,
                None,
            )
            self._subs.append(sub)

    def on_disable(self):
        for sub in self._subs:
            self.bus.signal_unsubscribe(sub)
        self._subs = []
        self._wasplaying = False

    def _on_active_changed(self, connection, sender, path, interface, signal, params, *user_data):
        try:
            active = params.unpack()[0]
        except (IndexError, TypeError):
            return
        logging.debug('Screensaver ActiveChanged: {}'.format(active))
        if active:
            self._wasplaying = self.window.playing
            self.window.pause()
        elif self._wasplaying:
            self.window.user_play()
            self._wasplaying = False
