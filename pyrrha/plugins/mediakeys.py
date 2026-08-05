# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Ported from Pithos' plugins/mediakeys.py (C) 2010-2012 Kevin Mehall.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Media-key support via the GNOME / MATE SettingsDaemon D-Bus interface.

This is the classic desktop-daemon grab that GNOME and MATE expose. On KDE
Plasma there is no such daemon — there, hardware media keys are delivered
through MPRIS instead (see :mod:`pyrrha.plugins.mpris`), so this plugin simply
finds no daemon and disables itself.

The GTK ``window-state-event`` focus tracking and the X11 Keybinder fallback
from Pithos are replaced with a small Qt event filter that re-grabs the keys
whenever the window is activated (GNOME hands the keys to the last-focused app).
"""

import logging

from gi.repository import GLib, Gio

from PySide6.QtCore import QEvent, QObject

from .. import APP_ID
from ..plugin import PyrrhaPlugin


class _ActivationFilter(QObject):
    """Calls back whenever the watched window becomes active."""

    def __init__(self, on_activate):
        super().__init__()
        self._on_activate = on_activate

    def eventFilter(self, obj, event):
        if event.type() == QEvent.WindowActivate:
            self._on_activate()
        return False


class MediaKeyPlugin(PyrrhaPlugin):
    preference = 'enable_mediakeys'
    description = 'Control playback with media keys (GNOME/MATE; KDE uses MPRIS)'

    mediakeys = None
    de_busnames = [
        ('gnome', 'org.gnome.SettingsDaemon.MediaKeys'),
        ('gnome', 'org.gnome.SettingsDaemon'),
        ('mate', 'org.mate.SettingsDaemon'),
    ]

    def grab_media_keys(self):
        self.mediakeys.call(
            'GrabMediaPlayerKeys', GLib.Variant('(su)', (APP_ID, 0)),
            Gio.DBusCallFlags.NONE, -1, None, None)

    def release_media_keys(self):
        self.mediakeys.call(
            'ReleaseMediaPlayerKeys', GLib.Variant('(s)', (APP_ID,)),
            Gio.DBusCallFlags.NONE, -1, None, None)

    def mediakey_signal(self, proxy, sender, signal, param, userdata=None):
        if signal != 'MediaPlayerKeyPressed':
            return
        app, action = param.unpack()
        if app != APP_ID:
            return
        if action == 'Play':
            self.window.playpause_notify()
        elif action == 'Next':
            self.window.next_song()
        elif action == 'Previous':
            self.window.bring_to_top()
        elif action in ('Stop', 'Pause'):
            self.window.user_pause()

    def on_prepare(self):
        # A fresh, mutable copy so repeated prepare cycles start over.
        self._remaining = list(self.de_busnames)
        self._filter = None
        self._mediakey_hook = None

        def on_new_finish(source, result, data):
            try:
                mediakeys = Gio.DBusProxy.new_finish(result)
            except GLib.Error as e:
                logging.debug(e)
                self._try_next_or_fail()
                return
            if mediakeys.get_name_owner():
                self.mediakeys = mediakeys
                self.prepare_complete()
            else:
                self._try_next_or_fail()

        def get_bus(de, bus_name):
            Gio.DBusProxy.new(
                self.bus, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None,
                bus_name, '/org/{}/SettingsDaemon/MediaKeys'.format(de),
                'org.{}.SettingsDaemon.MediaKeys'.format(de), None,
                on_new_finish, None)

        self._get_bus = get_bus

        if self.bus:
            self._try_next_or_fail()
        else:
            self.prepare_complete(error='No DBus connection for media keys.')

    def _try_next_or_fail(self):
        if self._remaining:
            de, busname = self._remaining.pop(0)
            self._get_bus(de, busname)
        else:
            self.prepare_complete(
                error='No GNOME/MATE media-key daemon found (KDE uses MPRIS).')

    def on_enable(self):
        self._mediakey_hook = self.mediakeys.connect('g-signal', self.mediakey_signal)
        self._filter = _ActivationFilter(self.grab_media_keys)
        self.window.installEventFilter(self._filter)
        self.grab_media_keys()
        logging.info('Bound media keys via {}'.format(
            self.mediakeys.props.g_interface_name))

    def on_disable(self):
        if self._mediakey_hook:
            self.mediakeys.disconnect(self._mediakey_hook)
            self._mediakey_hook = None
        if self._filter is not None:
            self.window.removeEventFilter(self._filter)
            self._filter = None
        self.release_media_keys()
        logging.info('Disabled dbus mediakey bindings')
