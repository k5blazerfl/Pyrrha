# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Ported from Pithos' plugins/notify.py (C) 2010-2012 Kevin Mehall.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Desktop notifications on song change.

Pithos used ``Gio.Application.send_notification``, which needs a GApplication.
Pyrrha has none (it runs on Qt), so this talks to the freedesktop
``org.freedesktop.Notifications`` service directly over D-Bus — the same daemon
GNOME and KDE both provide. That also gives real action buttons (Skip / click to
focus) and in-place replacement of the previous notification via ``replaces_id``.

Notifications are only shown while the window is *not* active (matching Pithos):
if you're already looking at Pyrrha there's nothing to notify. Album art usually
arrives a moment after the song starts, so when it does we refresh the same
notification in place so the cover shows.
"""

import logging

from gi.repository import Gio, GLib

from .. import APP_ID
from ..plugin import PyrrhaPlugin
from ..appicon import ICON_PATH

NOTIFY_NAME = 'org.freedesktop.Notifications'
NOTIFY_PATH = '/org/freedesktop/Notifications'
# Visual icon shown on the notification (a file path is accepted here).
APP_ICON = ICON_PATH
# Links the notification to the installed .desktop file (app association).
DESKTOP_ENTRY = APP_ID


class NotifyPlugin(PyrrhaPlugin):
    preference = 'notify'
    description = 'Shows notifications on song change'

    def on_prepare(self):
        if self.bus is None:
            self.prepare_complete(error='Failed to connect to DBus')
            return
        self._proxy = None
        self._last_id = 0
        self._notified_song = None
        self._shown_art = False
        self._song_conn = None
        self._meta_conn = None
        self._action_hook = None
        self._aboutToQuit = None

        def on_ready(source, result, data):
            try:
                self._proxy = Gio.DBusProxy.new_finish(result)
            except GLib.Error as e:
                logging.warning('Notifications service unavailable: {}'.format(e))
                self.prepare_complete(error='No notifications service found.')
                return
            self.prepare_complete()

        Gio.DBusProxy.new(
            self.bus, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None,
            NOTIFY_NAME, NOTIFY_PATH, NOTIFY_NAME, None, on_ready, None)

    def on_enable(self):
        self._song_conn = (self.window.song_changed, self._on_song_changed)
        self.window.song_changed.connect(self._on_song_changed)
        self._meta_conn = (self.window.metadata_changed, self._on_metadata_changed)
        self.window.metadata_changed.connect(self._on_metadata_changed)
        self._action_hook = self._proxy.connect('g-signal', self._on_daemon_signal)
        app = self.window.app
        self._aboutToQuit = app.aboutToQuit.connect(self._withdraw)

    def on_disable(self):
        self._withdraw()
        for pair in (self._song_conn, self._meta_conn):
            if pair:
                signal, slot = pair
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self._song_conn = self._meta_conn = None
        if self._action_hook:
            self._proxy.disconnect(self._action_hook)
            self._action_hook = None
        if self._aboutToQuit is not None:
            try:
                self.window.app.aboutToQuit.disconnect(self._withdraw)
            except (RuntimeError, TypeError):
                pass
            self._aboutToQuit = None

    # -- signal handlers ---------------------------------------------------
    def _on_song_changed(self, song=None):
        window = self.window
        if window.isActiveWindow():
            # The window is focused; withdraw any stale notification (KDE won't
            # auto-dismiss like GNOME Shell does) and don't post a new one.
            self._withdraw()
            return
        song = window.current_song
        if song is None:
            return
        self._notified_song = song
        self._shown_art = bool(song.artUrl)
        self._notify(song)

    def _on_metadata_changed(self, song=None):
        # When the album art finally arrives for the notified song, refresh the
        # existing notification in place so the cover shows.
        if (song is not None and song is self._notified_song and not self._shown_art
                and song.artUrl and not self.window.isActiveWindow()):
            self._shown_art = True
            self._notify(song)

    def _on_daemon_signal(self, proxy, sender, signal, params):
        if signal == 'ActionInvoked':
            nid, action = params.unpack()
            if nid != self._last_id:
                return
            if action == 'skip':
                self.window.next_song()
            elif action == 'default':
                self.window.bring_to_top()
        elif signal == 'NotificationClosed':
            nid = params.unpack()[0]
            if nid == self._last_id:
                self._last_id = 0

    # -- D-Bus plumbing ----------------------------------------------------
    def _notify(self, song):
        icon = APP_ICON
        hints = {'desktop-entry': GLib.Variant('s', DESKTOP_ENTRY)}
        if song.artUrl and song.artUrl.startswith('file://'):
            path = GLib.filename_from_uri(song.artUrl)[0]
            hints['image-path'] = GLib.Variant('s', path)

        # 'default' = activated when the notification body is clicked.
        actions = ['default', '', 'skip', _('Skip')]

        args = GLib.Variant('(susssasa{sv}i)', (
            'Pyrrha',          # app_name
            self._last_id,     # replaces_id (0 = new)
            icon,              # app_icon
            song.artist,       # summary  (matches GNOME Shell's layout)
            song.title,        # body
            actions,
            hints,
            -1,                # expire_timeout (daemon default)
        ))

        def on_sent(source, result, data):
            try:
                self._last_id = source.call_finish(result).unpack()[0]
            except GLib.Error as e:
                logging.warning('Failed to send notification: {}'.format(e))

        self._proxy.call('Notify', args, Gio.DBusCallFlags.NONE, -1, None, on_sent, None)

    def _withdraw(self, *ignore):
        if self._last_id and self._proxy is not None:
            self._proxy.call(
                'CloseNotification', GLib.Variant('(u)', (self._last_id,)),
                Gio.DBusCallFlags.NONE, -1, None, None, None)
            self._last_id = 0
