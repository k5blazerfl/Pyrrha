# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Ported from Pithos' plugins/lastfm.py (C) 2010-2012 Kevin Mehall.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Scrobble to Last.fm.

Uses ``pylast`` (optional dependency; the plugin disables itself with a note if
it is missing). Authorization is Last.fm's web flow: *Authorize* opens the
browser, then *Finish* exchanges the token for a session key, which is stored in
the plugin's ``data`` GSetting. While enabled, the current track is sent as
"now playing" on song change and scrobbled on song end (per Last.fm's rules).
Network calls run on Pyrrha's worker thread.
"""

import logging
import time
from enum import Enum

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout,
)

from ..plugin import PyrrhaPlugin
from ..worker import Worker

# getting an API account: http://www.last.fm/api/account
API_KEY = '997f635176130d5d6fe3a7387de601a8'
API_SECRET = '3243b876f6bf880b923a3c9fb955720c'


class LastfmPlugin(PyrrhaPlugin):
    preference = 'enable_lastfm'
    description = 'Scrobble songs to Last.fm'

    def on_prepare(self):
        try:
            import pylast
        except ImportError:
            self.prepare_complete(error='pylast not found')
            return
        self.pylast = pylast
        self.worker = Worker()
        self.network = None
        self._really_enabled = False
        self._handlers = []
        # Radio scrobbling state: the currently-playing ICY track and when it
        # started, so the previous track can be scrobbled when the title flips.
        self._radio_key = None
        self._radio_start = None
        self.preferences_dialog = LastFmAuth(pylast, self.settings, self.window)
        self.preferences_dialog.lastfm_authorized.connect(self._on_authorized)
        self.prepare_complete()

    def on_enable(self):
        if self.settings['data']:
            self._enable_real()
        else:
            # Not authorized yet — prompt for it.
            self.preferences_dialog.show()

    def _on_authorized(self, auth_state):
        if auth_state is AuthState.AUTHORIZED:
            self._enable_real()
        elif auth_state is AuthState.NOT_AUTHORIZED:
            self.on_disable()

    def _enable_real(self):
        self._connect(self.settings['data'])
        self._really_enabled = True
        if self.window.current_song:
            self._on_song_changed(self.window.current_song)
        pairs = [
            (self.window.song_ended, self._on_song_ended),
            (self.window.song_changed, self._on_song_changed),
            # Radio has no per-track song_changed; its ICY now-playing arrives
            # as metadata_changed, so scrobble radio from there instead.
            (self.window.metadata_changed, self._on_metadata_changed),
        ]
        for signal, slot in pairs:
            signal.connect(slot)
        self._handlers = pairs
        logging.debug('Last.fm plugin fully enabled')

    def on_disable(self):
        for signal, slot in self._handlers:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._handlers = []
        self._really_enabled = False

    def _connect(self, session_key):
        get_network = getattr(self.pylast, 'LastFMNetwork', None) or self.pylast.get_lastfm_network
        self.network = get_network(api_key=API_KEY, api_secret=API_SECRET,
                                   session_key=session_key)

    def _on_song_changed(self, song=None):
        song = song or self.window.current_song
        if song is None or self.network is None:
            return
        if getattr(self.window, 'is_radio', False):
            # A new station started; drop any pending radio track. now-playing
            # for radio is driven by ICY metadata, not the station row.
            self._radio_key = self._radio_start = None
            return

        def err(e):
            logging.error('Failed to update Last.fm now playing. Error: {}'.format(e))

        def ok(*ignore):
            logging.debug('Updated Last.fm now playing: {} by {}'.format(song.title, song.artist))

        self.worker.send(self.network.update_now_playing,
                         (song.artist, song.title, song.album), ok, err)

    def _on_song_ended(self, song=None):
        if song is None or self.network is None:
            return
        if getattr(self.window, 'is_radio', False):
            # Leaving a station: scrobble whatever was playing on it.
            self._scrobble_radio_pending()
            return

        def err(e):
            logging.error('Failed to scrobble to Last.fm. Error: {}'.format(e))

        def ok(*ignore):
            logging.info('Scrobbled {} by {} to Last.fm'.format(song.title, song.artist))

        duration = song.get_duration_sec()
        position = song.get_position_sec() or 0
        # Last.fm scrobble rules: >30s track, played past halfway or 4 minutes.
        if not song.is_ad and duration > 30 and (position > 240 or position > duration / 2):
            args = (song.artist, song.title, int(song.start_time), song.album,
                    None, None, int(duration))
            self.worker.send(self.network.scrobble, args, ok, err)

    def _on_metadata_changed(self, song=None):
        """Radio now-playing/scrobbling. Fires on every metadata_changed, but
        only acts when the current radio station's ICY title actually changes:
        scrobble the previous track, then mark the new one as now-playing."""
        if self.network is None or not getattr(self.window, 'is_radio', False):
            return
        if not self.window.settings['scrobble-radio']:
            return
        song = song or self.window.current_song
        if song is None or song is not self.window.current_song:
            return
        key = (song.artist, song.title)
        if key == self._radio_key:
            return                          # same track; nothing to do
        self._scrobble_radio_pending()      # scrobble the outgoing track
        self._radio_key = key
        self._radio_start = time.time()

        def err(e):
            logging.error('Failed to update Last.fm now playing. Error: {}'.format(e))

        self.worker.send(self.network.update_now_playing,
                         (song.artist, song.title, song.album), lambda *a: None, err)

    def _scrobble_radio_pending(self):
        """Scrobble the pending radio track if it played long enough, then clear
        it. Stream tracks have no known length, so we use elapsed wall-clock
        against Last.fm's 30s floor."""
        key, start = self._radio_key, self._radio_start
        self._radio_key = self._radio_start = None
        if (self.network is None or not key or not start
                or not self.window.settings['scrobble-radio']):
            return
        artist, title = key
        elapsed = time.time() - start
        if not artist or not title or elapsed <= 30:
            return

        def err(e):
            logging.error('Failed to scrobble to Last.fm. Error: {}'.format(e))

        def ok(*ignore):
            logging.info('Scrobbled radio track {} by {} to Last.fm'.format(title, artist))

        self.worker.send(self.network.scrobble,
                         (artist, title, int(start)), ok, err)


class AuthState(Enum):
    NOT_AUTHORIZED = 0
    BEGAN_AUTHORIZATION = 1
    AUTHORIZED = 2


class LastFmAuth(QDialog):
    lastfm_authorized = Signal(object)  # AuthState

    def __init__(self, pylast, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Last.fm')
        self.setModal(True)
        self.pylast = pylast
        self.settings = settings
        self.worker = Worker()
        self.auth_url = ''
        self._sg = None

        self.auth_state = AuthState.AUTHORIZED if settings['data'] else AuthState.NOT_AUTHORIZED

        self.label = QLabel()
        self.button = QPushButton()
        self.button.clicked.connect(self._on_clicked)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.hide)

        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.button)
        layout.addWidget(close)
        self._set_widget_text()

    def _set_widget_text(self):
        if self.auth_state is AuthState.AUTHORIZED:
            self.button.setText(_('Deauthorize'))
            self.label.setText(_('Pyrrha is authorized with Last.fm'))
        elif self.auth_state is AuthState.NOT_AUTHORIZED:
            self.button.setText(_('Authorize'))
            self.label.setText(_('Pyrrha is not authorized with Last.fm'))
        else:  # BEGAN_AUTHORIZATION
            self.button.setText(_('Finish'))
            self.label.setText(_('Click Finish once you have authorized in the browser'))

    def _setkey(self, key):
        if not key:
            self.auth_state = AuthState.NOT_AUTHORIZED
            self.settings.reset('data')
            logging.debug('Last.fm auth key cleared')
        else:
            self.auth_state = AuthState.AUTHORIZED
            self.settings['data'] = key
            logging.debug('Got Last.fm auth key')
        self._set_widget_text()
        self.button.setEnabled(True)
        self.lastfm_authorized.emit(self.auth_state)

    def _begin(self):
        def err(e):
            logging.error('Failed to begin Last.fm authorization. Error: {}'.format(e))
            self._setkey('')

        def got_url(url):
            self.auth_url = url
            logging.debug('Opening Last.fm auth url')
            QDesktopServices.openUrl(QUrl(url))
            self.button.setEnabled(True)

        self.auth_state = AuthState.BEGAN_AUTHORIZATION
        get_network = getattr(self.pylast, 'LastFMNetwork', None) or self.pylast.get_lastfm_network
        self._sg = self.pylast.SessionKeyGenerator(
            get_network(api_key=API_KEY, api_secret=API_SECRET))
        self._set_widget_text()
        self.button.setEnabled(False)
        self.worker.send(self._sg.get_web_auth_url, (), got_url, err)

    def _finish(self):
        def err(e):
            logging.error('Failed to finish Last.fm authorization. Error: {}'.format(e))
            self._setkey('')

        self.button.setEnabled(False)
        self.worker.send(self._sg.get_web_auth_session_key, (self.auth_url,),
                         self._setkey, err)

    def _on_clicked(self):
        if self.auth_state is AuthState.NOT_AUTHORIZED:
            self._begin()
        elif self.auth_state is AuthState.BEGAN_AUTHORIZATION:
            self._finish()
        else:  # AUTHORIZED
            self._setkey('')
