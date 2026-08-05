# -*- coding: utf-8; tab-width: 4; indent-tabs-mode: nil; -*-
# Copyright (C) 2010 Kevin Mehall <km@kevinmehall.net>
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3, as published
# by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranties of
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR
# PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Vendored from Pithos (pithos/pandora/fake.py) for Pyrrha and made headless:
# the original opened a small GTK "failure tester" window to toggle auth/slowness
# at runtime; that was Pyrrha's last GTK dependency, so it is replaced with plain
# flags. The mock service behaviour (stations, playlists, the public test file)
# is unchanged, giving Pyrrha an offline `--test` mode with no GTK.

import logging
import time

from .pandora import *

TEST_FILE = "http://pithos.github.io/testfile.aac"


class _Flag:
    """Headless stand-in for the old GTK check buttons."""

    def __init__(self, active=False):
        self._active = active

    def get_active(self):
        return self._active

    def set_active(self, active):
        self._active = active


class FakePandora(Pandora):
    def __init__(self):
        super().__init__()
        self.counter = 0
        # Previously GTK check buttons in a debug window:
        #   auth_check  - connect() authenticates; until then calls fail.
        #   time_check  - when set, simulate a slow (10s) network.
        self.auth_check = _Flag(False)
        self.time_check = _Flag(False)
        logging.info("Using test mode")

    def count(self):
        self.counter += 1
        return self.counter

    def maybe_fail(self):
        if self.time_check.get_active():
            logging.info("fake: Going to sleep for 10s")
            time.sleep(10)
        if not self.auth_check.get_active():
            logging.info("fake: We're deauthenticated...")
            raise PandoraAuthTokenInvalid("Auth token invalid", "AUTH_INVALID_TOKEN")

    def set_authenticated(self):
        self.auth_check.set_active(True)

    def json_call(self, method, args=None, https=False, blowfish=True):
        time.sleep(1)
        self.maybe_fail()

        if method == 'user.getStationList':
            return {'stations': [
                {'stationId': '987', 'stationToken': '345434', 'isShared': False, 'isQuickMix': False, 'stationName': "Test Station 1"},
                {'stationId': '321', 'stationToken': '453544', 'isShared': False, 'isQuickMix': True, 'stationName': "Fake's QuickMix",
                    'quickMixStationIds': ['987', '343']},
                {'stationId': '432', 'stationToken': '345485', 'isShared': False, 'isQuickMix': False, 'stationName': "Test Station 2"},
                {'stationId': '254', 'stationToken': '345415', 'isShared': False, 'isQuickMix': False, 'stationName': "Test Station 4 - Out of Order"},
                {'stationId': '343', 'stationToken': '345435', 'isShared': False, 'isQuickMix': False, 'stationName': "Test Station 3"},
            ]}
        elif method == 'station.getPlaylist':
            stationId = self.get_station_by_token(args['stationToken']).id
            return {'items': [self.makeFakeSong(stationId) for i in range(4)]}
        elif method == 'music.search':
            return {'artists': [
                        {'score': 90, 'musicToken': '988', 'artistName': "artistName"},
                    ],
                    'songs': [
                        {'score': 80, 'musicToken': '238', 'songName': "SongName", 'artistName': "ArtistName"},
                    ],
                    }
        elif method == 'station.createStation':
            return {'stationId': '999', 'stationToken': '345433', 'isShared': False, 'isQuickMix': False, 'stationName': "Added Station"}
        elif method == 'station.addFeedback':
            return {'feedbackId': '1234'}
        elif method in ('user.setQuickMix',
                        'station.deleteFeedback',
                        'station.transformSharedStation',
                        'station.renameStation',
                        'station.deleteStation',
                        'user.sleepSong',
                        'bookmark.addSongBookmark',
                        'bookmark.addArtistBookmark',
                        ):
            return 1
        else:
            logging.error("Invalid method %s" % method)

    def connect(self, client, user, password):
        self.set_authenticated()
        self.get_stations()

    def get_station_by_token(self, token):
        for i in self.stations:
            if i.idToken == token:
                return i

    def makeFakeSong(self, stationId):
        c = self.count()
        audio_url = TEST_FILE + '?val=' + '0' * 48
        return {
            'albumName': "AlbumName",
            'artistName': "ArtistName",
            'audioUrlMap': {
                'highQuality': {
                    'encoding': 'aac',
                    'bitrate': '32',
                    'audioUrl': audio_url
                },
                'mediumQuality': {
                    'encoding': 'aac',
                    'bitrate': '32',
                    'audioUrl': audio_url
                },
                'lowQuality': {
                    'encoding': 'aac',
                    'bitrate': '32',
                    'audioUrl': audio_url
                },
            },
            'trackLength': 121,
            'trackGain': 0,
            'trackToken': '5908540384',
            'songRating': 1 if c % 3 == 0 else 0,
            'stationId': stationId,
            'songName': 'Test song %i' % c,
            'songDetailUrl': 'http://pithos.github.io/',
            'albumDetailUrl': 'http://pithos.github.io/',
            'albumArtUrl': 'http://pithos.github.io/img/pithos_logo.png',
            'songExplorerUrl': 'http://pithos.github.io/test-song.xml',
        }
