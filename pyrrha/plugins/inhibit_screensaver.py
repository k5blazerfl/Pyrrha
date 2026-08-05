# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Ported from Pithos' plugins/inhibit_screensaver.py (C) 2017 Jason Gray.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Keep the session from going idle while music is playing.

Pithos used ``Gtk.Application.inhibit``; Pyrrha has no GtkApplication, so this
talks to the freedesktop ``org.freedesktop.ScreenSaver`` service over D-Bus
(supported by KDE, GNOME and most desktops). An inhibit is taken while playing
and released on pause/stop or when the plugin is disabled.
"""

import logging

from gi.repository import Gio, GLib

from ..plugin import PyrrhaPlugin

SS_NAME = 'org.freedesktop.ScreenSaver'
SS_PATH = '/org/freedesktop/ScreenSaver'


class InhibitScreensaverPlugin(PyrrhaPlugin):
    preference = 'enable_inhibitscreensaver'
    description = 'Prevent the session from going idle while playing'

    def on_prepare(self):
        if self.bus is None:
            self.prepare_complete(error='Failed to connect to DBus')
            return
        self._proxy = None
        self._cookie = 0
        self._playing = None
        self._conn = None

        def on_ready(source, result, data):
            try:
                self._proxy = Gio.DBusProxy.new_finish(result)
            except GLib.Error as e:
                logging.warning('ScreenSaver service unavailable: {}'.format(e))
                self.prepare_complete(error='No screensaver service found.')
                return
            self.prepare_complete()

        Gio.DBusProxy.new(
            self.bus, Gio.DBusProxyFlags.NONE, None,
            SS_NAME, SS_PATH, SS_NAME, None, on_ready, None)

    def on_enable(self):
        self._conn = self._on_status_changed
        self.window.play_state_changed.connect(self._conn)
        self._on_status_changed()

    def on_disable(self):
        if self._conn is not None:
            try:
                self.window.play_state_changed.disconnect(self._conn)
            except (RuntimeError, TypeError):
                pass
            self._conn = None
        self._uninhibit()

    def _on_status_changed(self, *ignore):
        playing = self.window.playing
        if self._playing != playing:
            self._playing = playing
            if playing:
                self._inhibit()
            else:
                self._uninhibit()

    def _inhibit(self):
        if self._cookie or self._proxy is None:
            return

        def on_done(source, result, data):
            try:
                self._cookie = source.call_finish(result).unpack()[0]
            except GLib.Error as e:
                logging.warning('Failed to inhibit screensaver: {}'.format(e))

        self._proxy.call(
            'Inhibit', GLib.Variant('(ss)', ('Pyrrha', 'Playing music')),
            Gio.DBusCallFlags.NONE, -1, None, on_done, None)

    def _uninhibit(self):
        if self._cookie and self._proxy is not None:
            self._proxy.call(
                'UnInhibit', GLib.Variant('(u)', (self._cookie,)),
                Gio.DBusCallFlags.NONE, -1, None, None, None)
        self._cookie = 0
        self._playing = None
