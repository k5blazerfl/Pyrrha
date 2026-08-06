# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Ported from Pithos' plugins/mpris.py
#   (C) 2011 Rick Spencer, 2011-2012 Kevin Mehall, 2017 Jason Gray.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""MPRIS2 support.

Exports ``org.mpris.MediaPlayer2`` + ``.Player`` (plus Playlists / TrackList and
Pithos' ratings extension) on the session bus. On KDE Plasma and modern GNOME
this is also what makes the hardware media keys (Play/Pause/Next/Stop) control
Pyrrha — the desktop forwards them to the registered MPRIS player.

The D-Bus service object is reused verbatim from Pithos (pure Gio, no GTK). Only
the wiring to the window changed: the window's Qt signals and the ``SongsModel``
replace Pithos' GObject signals and ``Gtk.ListStore``.
"""

import codecs
import logging
import math

from gi.repository import GLib, Gio

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QVBoxLayout

# Pure-Gio D-Bus service helper (no GTK involved), vendored from Pithos.
from ..dbus_util.DBusServiceObject import (
    DBusServiceObject, dbus_method, dbus_signal, dbus_property,
)

from .. import APP_ID
from ..plugin import PyrrhaPlugin

# Base D-Bus object path derived from the app id (e.g. /io/github/.../Pyrrha).
_OBJ_BASE = '/' + APP_ID.replace('.', '/')


class MprisPlugin(PyrrhaPlugin):
    preference = 'enable_mpris'
    description = 'Control with external programs and media keys (via MPRIS)'

    def on_prepare(self):
        if self.bus is None:
            self.prepare_complete(error='Failed to connect to DBus')
            return
        try:
            self.mpris = PyrrhaMprisService(self.window, connection=self.bus)
        except Exception as e:
            logging.warning('Failed to create DBus mpris service: {}'.format(e))
            self.prepare_complete(error='Failed to create DBus mpris service')
        else:
            self._interceptor = None
            self.preferences_dialog = MprisPrefsDialog(self.window, self.settings)
            self.prepare_complete()

    def on_enable(self):
        self.mpris.connect()
        # Register a close interceptor; it hides the window instead of quitting
        # only while the "hide on close" option is on (settings['data']).
        self._interceptor = self._hide_on_close
        self.window.close_interceptors.append(self._interceptor)

    def _hide_on_close(self):
        return self.settings['data'] == 'True'

    def on_disable(self):
        self.mpris.disconnect()
        if self._interceptor in self.window.close_interceptors:
            self.window.close_interceptors.remove(self._interceptor)
        self._interceptor = None


class PyrrhaMprisService(DBusServiceObject):
    MEDIA_PLAYER2_IFACE = 'org.mpris.MediaPlayer2'
    MEDIA_PLAYER2_PLAYER_IFACE = 'org.mpris.MediaPlayer2.Player'
    MEDIA_PLAYER2_PLAYLISTS_IFACE = 'org.mpris.MediaPlayer2.Playlists'
    MEDIA_PLAYER2_TRACKLIST_IFACE = 'org.mpris.MediaPlayer2.TrackList'
    MEDIA_PLAYER2_RATINGS_IFACE = 'org.mpris.MediaPlayer2.ExtensionPyrrhaRatings'

    TRACK_OBJ_PATH = _OBJ_BASE + '/TrackId/'
    NO_TRACK_OBJ_PATH = '/org/mpris/MediaPlayer2/TrackList/NoTrack'
    PLAYLIST_OBJ_PATH = _OBJ_BASE + '/PlaylistId/'

    NO_TRACK_METADATA = {'mpris:trackid': GLib.Variant('o', NO_TRACK_OBJ_PATH)}

    def __init__(self, window, **kwargs):
        super().__init__(object_path='/org/mpris/MediaPlayer2', **kwargs)
        self.window = window
        self.bus_id = 0
        self._qt_conns = []
        self._volumechange_handler_id = None

    def _reset(self):
        self._has_thumbprint_radio = False
        self._volume = math.pow(self.window.player.props.volume, 1.0 / 3.0)
        self._metadata = self.NO_TRACK_METADATA
        self._metadata_list = [self.NO_TRACK_METADATA]
        self._tracks = [self.NO_TRACK_OBJ_PATH]
        self._playback_status = 'Stopped'
        self._playlists = [('/', '', '')]
        self._current_playlist = False, ('/', '', '')
        self._orderings = ['CreationDate']

    def connect(self):
        self._reset()

        def on_name_acquired(connection, name):
            logging.info('Got bus name: {}'.format(name))
            self._update_handlers()
            self._connect_handlers()

        self.bus_id = Gio.bus_own_name_on_connection(
            self.connection,
            'org.mpris.MediaPlayer2.Pyrrha',
            Gio.BusNameOwnerFlags.NONE,
            on_name_acquired,
            None,
        )

    def disconnect(self):
        self._disconnect_handlers()
        if self.bus_id:
            Gio.bus_unown_name(self.bus_id)
            self.bus_id = 0

    # -- handler wiring (Qt signals) ---------------------------------------
    def _update_handlers(self):
        """Sync dynamic props in case MPRIS was enabled mid-song."""
        window = self.window
        station = window.current_station
        song = window.current_song
        if station:
            self._current_playlist_handler(window, station)
            if window.pandora and window.pandora.stations:
                self._update_playlists_handler(window, window.pandora.stations)
        if song:
            self._songs_added_handler(window, 4)
            self._metadatachange_handler(window, song)
            self._playstate_handler(window, window.playing)
        self._sort_order_handler()

    def _connect_handlers(self):
        window = self.window
        # (signal, slot) pairs so we can disconnect precisely later.
        pairs = [
            (window.metadata_changed,
             lambda song: self._metadatachange_handler(window, song)),
            (window.play_state_changed,
             lambda state: self._playstate_handler(window, state)),
            (window.buffering_finished,
             lambda position: self.Seeked(position // 1000)),
            (window.station_changed_sig,
             lambda station: self._current_playlist_handler(window, station)),
            (window.stations_processed,
             lambda stations: self._update_playlists_handler(window, stations)),
            (window.station_added_sig,
             lambda station: self._add_playlist_handler(window, station)),
            (window.station_removed_sig,
             lambda station: self._remove_playlist_handler(window, station)),
            (window.station_renamed_sig,
             lambda data: self._rename_playlist_handler(window, data)),
            (window.songs_added,
             lambda count: self._songs_added_handler(window, count)),
        ]
        self._qt_conns = []
        for signal, slot in pairs:
            signal.connect(slot)
            self._qt_conns.append((signal, slot))

        # The Gst element keeps its GObject handler id; settings changes come
        # through the Qt ``changed`` signal, filtered by key in the handler.
        self._volumechange_handler_id = window.player.connect(
            'notify::volume', self._volumechange_handler)
        window.settings.changed.connect(self._sort_order_handler)

    def _disconnect_handlers(self):
        window = self.window
        for signal, slot in self._qt_conns:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._qt_conns = []
        if self._volumechange_handler_id:
            window.player.disconnect(self._volumechange_handler_id)
            self._volumechange_handler_id = None
        try:
            window.settings.changed.disconnect(self._sort_order_handler)
        except (RuntimeError, TypeError):
            pass

    # -- handlers ----------------------------------------------------------
    def _sort_order_handler(self, key=None):
        if key is not None and key != 'sort-stations':
            return
        new = ['Alphabetical'] if self.window.settings['sort-stations'] else ['CreationDate']
        if self._orderings != new:
            self._orderings = new
            self.PropertiesChanged(
                self.MEDIA_PLAYER2_PLAYLISTS_IFACE,
                {'Orderings': GLib.Variant('as', self._orderings)}, [])

    def _update_playlists_handler(self, window, stations):
        self._has_thumbprint_radio = len(stations) > 1 and stations[1].isThumbprint
        self._playlists = [(self.PLAYLIST_OBJ_PATH + s.id, s.name, '') for s in stations]
        self.PropertiesChanged(
            self.MEDIA_PLAYER2_PLAYLISTS_IFACE,
            {'PlaylistCount': GLib.Variant('u', len(self._playlists))}, [])

    def _current_playlist_handler(self, window, station):
        new = (self.PLAYLIST_OBJ_PATH + station.id, station.name, '')
        if self._current_playlist != (True, new):
            self._current_playlist = (True, new)
            self.PropertiesChanged(
                self.MEDIA_PLAYER2_PLAYLISTS_IFACE,
                {'ActivePlaylist': GLib.Variant('(b(oss))', self._current_playlist)}, [])

    def _playlist_id(self, entry):
        # Station id from a playlist object-path (proper prefix removal).
        return entry[0][len(self.PLAYLIST_OBJ_PATH):]

    def _add_playlist_handler(self, window, station):
        new_playlist = (self.PLAYLIST_OBJ_PATH + station.id, station.name, '')
        if new_playlist not in self._playlists:
            # After QuickMix (and Thumbprint Radio, if present).
            self._playlists.insert(2 if self._has_thumbprint_radio else 1, new_playlist)
            self.PropertiesChanged(
                self.MEDIA_PLAYER2_PLAYLISTS_IFACE,
                {'PlaylistCount': GLib.Variant('u', len(self._playlists))}, [])

    def _remove_playlist_handler(self, window, station):
        for index, playlist in enumerate(self._playlists):
            if self._playlist_id(playlist) == station.id:
                del self._playlists[index]
                self.PropertiesChanged(
                    self.MEDIA_PLAYER2_PLAYLISTS_IFACE,
                    {'PlaylistCount': GLib.Variant('u', len(self._playlists))}, [])
                break

    def _rename_playlist_handler(self, window, data):
        station_id, new_name = data
        for index, playlist in enumerate(self._playlists):
            if self._playlist_id(playlist) == station_id:
                self._playlists[index] = (self.PLAYLIST_OBJ_PATH + station_id, new_name, '')
                self.PlaylistChanged(self._playlists[index])
                break

    def _playstate_handler(self, window, state):
        play_state = 'Playing' if state else 'Paused'
        if self._playback_status != play_state:
            self._playback_status = play_state
            self.PropertiesChanged(
                self.MEDIA_PLAYER2_PLAYER_IFACE,
                {'PlaybackStatus': GLib.Variant('s', self._playback_status)}, [])

    def _volumechange_handler(self, player, spec):
        volume = math.pow(player.props.volume, 1.0 / 3.0)
        if self._volume != volume:
            self._volume = volume
            self.PropertiesChanged(
                self.MEDIA_PLAYER2_PLAYER_IFACE,
                {'Volume': GLib.Variant('d', self._volume)}, [])

    def _songs_added_handler(self, window, song_count):
        model = window.songs_model
        stop = len(model)
        start = max(0, stop - (song_count + 1))
        songs = [model.song_at(i) for i in range(start, stop)]
        songs = [s for s in songs if s is not None]
        if not songs:
            return
        self._tracks = [self._track_id_from_song(s) for s in songs]
        self._metadata_list = [self._get_metadata(window, s) for s in songs]
        self.TrackListReplaced(self._tracks, self._tracks[0])

    def _metadatachange_handler(self, window, song):
        if song.index < max(0, len(window.songs_model) - 5):
            return
        metadata = self._get_metadata(window, song)
        trackId = self._track_id_from_song(song)
        if trackId in self._tracks:
            for index, track_id in enumerate(self._tracks):
                if track_id == trackId and not self._metadata_equal(self._metadata_list[index], metadata):
                    self._metadata_list[index] = metadata
                    self.TrackMetadataChanged(trackId, metadata)
                    break
        if (song is window.current_song and not (song.tired or song.rating == 'ban') and
                not self._metadata_equal(self._metadata, metadata)):
            self._metadata = metadata
            self.PropertiesChanged(
                self.MEDIA_PLAYER2_PLAYER_IFACE,
                {'Metadata': GLib.Variant('a{sv}', self._metadata)}, [])

    def _get_metadata(self, window, song):
        userRating = 1.0 if song.rating == 'love' else 0.0
        duration = song.get_duration_sec() * 1000000
        rating_str = window.song_icon(song) or ''
        trackid = self._track_id_from_song(song)
        metadata = {
            'mpris:trackid': GLib.Variant('o', trackid),
            'xesam:title': GLib.Variant('s', song.title or 'Title Unknown'),
            'xesam:artist': GLib.Variant('as', [song.artist] or ['Artist Unknown']),
            'xesam:album': GLib.Variant('s', song.album or 'Album Unknown'),
            'xesam:userRating': GLib.Variant('d', userRating),
            'xesam:url': GLib.Variant('s', song.audioUrl),
            'mpris:length': GLib.Variant('x', duration),
            'pyrrha:rating': GLib.Variant('s', rating_str),
        }
        if song.artUrl is not None:
            metadata['mpris:artUrl'] = GLib.Variant('s', song.artUrl)
        return metadata

    def _metadata_equal(self, m1, m2):
        if len(m1) != len(m2):
            return False
        for key in m1.keys():
            if key not in m2 or not m1[key].equal(m2[key]):
                return False
        return True

    def _song_from_track_id(self, TrackId):
        if TrackId not in self._tracks or self.window.current_song_index is None:
            return
        model = self.window.songs_model
        stop = len(model)
        start = max(0, stop - 5)
        for i in range(start, stop):
            song = model.song_at(i)
            if song is not None and TrackId == self._track_id_from_song(song):
                return song

    def _track_id_from_song(self, song):
        return self.TRACK_OBJ_PATH + codecs.encode(bytes(song.trackToken, 'ascii'), 'hex').decode('ascii')

    # -- MediaPlayer2 properties ------------------------------------------
    @dbus_property(MEDIA_PLAYER2_IFACE, signature='b')
    def CanQuit(self):
        return True

    @dbus_property(MEDIA_PLAYER2_IFACE, signature='b')
    def Fullscreen(self):
        return False

    @Fullscreen.setter
    def Fullscreen(self, Fullscreen):
        pass

    @dbus_property(MEDIA_PLAYER2_IFACE, signature='b')
    def CanSetFullscreen(self):
        return False

    @dbus_property(MEDIA_PLAYER2_IFACE, signature='b')
    def CanRaise(self):
        return True

    @dbus_property(MEDIA_PLAYER2_IFACE, signature='b')
    def HasTrackList(self):
        return True

    @dbus_property(MEDIA_PLAYER2_IFACE, signature='s')
    def Identity(self):
        return 'Pyrrha'

    @dbus_property(MEDIA_PLAYER2_IFACE, signature='s')
    def DesktopEntry(self):
        return APP_ID

    @dbus_property(MEDIA_PLAYER2_IFACE, signature='as')
    def SupportedUriSchemes(self):
        return []

    @dbus_property(MEDIA_PLAYER2_IFACE, signature='as')
    def SupportedMimeTypes(self):
        return []

    # -- Player properties -------------------------------------------------
    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='s')
    def PlaybackStatus(self):
        return self._playback_status

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='s')
    def LoopStatus(self):
        return 'None'

    @LoopStatus.setter
    def LoopStatus(self, LoopStatus):
        pass

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='b')
    def Shuffle(self):
        return False

    @Shuffle.setter
    def Shuffle(self, Shuffle):
        pass

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='d')
    def Rate(self):
        return 1.0

    @Rate.setter
    def Rate(self, Rate):
        pass

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='a{sv}')
    def Metadata(self):
        return self._metadata

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='d')
    def Volume(self):
        return math.pow(self.window.player.get_property('volume'), 1.0 / 3.0)

    @Volume.setter
    def Volume(self, new_volume):
        self.window.player.set_property('volume', math.pow(new_volume, 3.0))

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='x')
    def Position(self):
        position = self.window.query_position()
        return position // 1000 if position is not None else 0

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='d')
    def MinimumRate(self):
        return 1.0

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='d')
    def MaximumRate(self):
        return 1.0

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='b')
    def CanGoNext(self):
        return True

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='b')
    def CanGoPrevious(self):
        return False

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='b')
    def CanPlay(self):
        return True

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='b')
    def CanPause(self):
        return True

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='b')
    def CanSeek(self):
        return False

    @dbus_property(MEDIA_PLAYER2_PLAYER_IFACE, signature='b')
    def CanControl(self):
        return True

    # -- Playlists / TrackList / Ratings properties -----------------------
    @dbus_property(MEDIA_PLAYER2_PLAYLISTS_IFACE, signature='(b(oss))')
    def ActivePlaylist(self):
        return self._current_playlist

    @dbus_property(MEDIA_PLAYER2_PLAYLISTS_IFACE, signature='u')
    def PlaylistCount(self):
        return len(self._playlists)

    @dbus_property(MEDIA_PLAYER2_PLAYLISTS_IFACE, signature='as')
    def Orderings(self):
        return self._orderings

    @dbus_property(MEDIA_PLAYER2_TRACKLIST_IFACE, signature='ao')
    def Tracks(self):
        return self._tracks

    @dbus_property(MEDIA_PLAYER2_TRACKLIST_IFACE, signature='b')
    def CanEditTracks(self):
        return False

    @dbus_property(MEDIA_PLAYER2_RATINGS_IFACE, signature='b')
    def HasPyrrhaExtension(self):
        return True

    # -- MediaPlayer2 methods ---------------------------------------------
    @dbus_method(MEDIA_PLAYER2_IFACE)
    def Raise(self):
        self.window.bring_to_top()

    @dbus_method(MEDIA_PLAYER2_IFACE)
    def Quit(self):
        self.window.quit()

    # -- Player methods ----------------------------------------------------
    @dbus_method(MEDIA_PLAYER2_PLAYER_IFACE)
    def Previous(self):
        pass

    @dbus_method(MEDIA_PLAYER2_PLAYER_IFACE)
    def Next(self):
        if not self.window.waiting_for_playlist:
            self.window.next_song()

    @dbus_method(MEDIA_PLAYER2_PLAYER_IFACE)
    def PlayPause(self):
        if self.window.current_song:
            self.window.playpause()

    @dbus_method(MEDIA_PLAYER2_PLAYER_IFACE)
    def Play(self):
        if self.window.current_song:
            self.window.play()

    @dbus_method(MEDIA_PLAYER2_PLAYER_IFACE)
    def Pause(self):
        if self.window.current_song:
            self.window.pause()

    @dbus_method(MEDIA_PLAYER2_PLAYER_IFACE)
    def Stop(self):
        if self.window.current_song:
            self.window.pause()

    @dbus_method(MEDIA_PLAYER2_PLAYER_IFACE, in_signature='x')
    def Seek(self, Offset):
        pass

    @dbus_method(MEDIA_PLAYER2_PLAYER_IFACE, in_signature='s')
    def OpenUri(self, Uri):
        pass

    @dbus_method(MEDIA_PLAYER2_PLAYER_IFACE, in_signature='ox')
    def SetPosition(self, TrackId, Position):
        pass

    # -- Playlists methods -------------------------------------------------
    @dbus_method(MEDIA_PLAYER2_PLAYLISTS_IFACE, in_signature='uusb', out_signature='a(oss)')
    def GetPlaylists(self, Index, MaxCount, Order, ReverseOrder):
        playlists = self._playlists[:]
        always_first = [playlists.pop(0)]  # QuickMix
        if self._has_thumbprint_radio and playlists:
            always_first.append(playlists.pop(0))
        if Order not in ('CreationDate', 'Alphabetical') or Order == 'Alphabetical':
            playlists = sorted(playlists, key=lambda p: p[1])
        if ReverseOrder:
            playlists.reverse()
        playlists = always_first + playlists[Index:MaxCount - len(always_first)]
        return playlists

    @dbus_method(MEDIA_PLAYER2_PLAYLISTS_IFACE, in_signature='o')
    def ActivatePlaylist(self, PlaylistId):
        stations = self.window.pandora.stations
        station_id = PlaylistId.strip(self.PLAYLIST_OBJ_PATH)
        for station in stations:
            if station.id == station_id:
                self.window.station_changed(station)
                break

    # -- TrackList methods -------------------------------------------------
    @dbus_method(MEDIA_PLAYER2_TRACKLIST_IFACE, in_signature='ao', out_signature='aa{sv}')
    def GetTracksMetadata(self, TrackIds):
        return [self._metadata_list[self._tracks.index(t)] for t in TrackIds if t in self._tracks]

    @dbus_method(MEDIA_PLAYER2_TRACKLIST_IFACE, in_signature='sob')
    def AddTrack(self, Uri, AfterTrack, SetAsCurrent):
        pass

    @dbus_method(MEDIA_PLAYER2_TRACKLIST_IFACE, in_signature='o')
    def RemoveTrack(self, TrackId):
        pass

    @dbus_method(MEDIA_PLAYER2_TRACKLIST_IFACE, in_signature='o')
    def GoTo(self, TrackId):
        song = self._song_from_track_id(TrackId)
        if song and song.index > self.window.current_song_index and not (song.tired or song.rating == 'ban'):
            self.window.start_song(song.index)

    # -- Ratings extension methods ----------------------------------------
    @dbus_method(MEDIA_PLAYER2_RATINGS_IFACE, in_signature='o')
    def LoveSong(self, TrackId):
        song = self._song_from_track_id(TrackId)
        if song:
            self.window.love_song(song=song)

    @dbus_method(MEDIA_PLAYER2_RATINGS_IFACE, in_signature='o')
    def BanSong(self, TrackId):
        song = self._song_from_track_id(TrackId)
        if song:
            self.window.ban_song(song=song)

    @dbus_method(MEDIA_PLAYER2_RATINGS_IFACE, in_signature='o')
    def TiredSong(self, TrackId):
        song = self._song_from_track_id(TrackId)
        if song:
            self.window.tired_song(song=song)

    @dbus_method(MEDIA_PLAYER2_RATINGS_IFACE, in_signature='o')
    def UnRateSong(self, TrackId):
        song = self._song_from_track_id(TrackId)
        if song:
            self.window.unrate_song(song=song)

    # -- signals -----------------------------------------------------------
    @dbus_signal(MEDIA_PLAYER2_PLAYER_IFACE, signature='x')
    def Seeked(self, Position):
        pass

    @dbus_signal(MEDIA_PLAYER2_PLAYLISTS_IFACE, signature='(oss)')
    def PlaylistChanged(self, Playlist):
        pass

    @dbus_signal(MEDIA_PLAYER2_TRACKLIST_IFACE, signature='aoo')
    def TrackListReplaced(self, Tracks, CurrentTrack):
        pass

    @dbus_signal(MEDIA_PLAYER2_TRACKLIST_IFACE, signature='a{sv}o')
    def TrackAdded(self, Metadata, AfterTrack):
        pass

    @dbus_signal(MEDIA_PLAYER2_TRACKLIST_IFACE, signature='o')
    def TrackRemoved(self, TrackId):
        pass

    @dbus_signal(MEDIA_PLAYER2_TRACKLIST_IFACE, signature='oa{sv}')
    def TrackMetadataChanged(self, TrackId, Metadata):
        pass

    def PropertiesChanged(self, interface, changed, invalidated):
        try:
            self.connection.emit_signal(
                None, '/org/mpris/MediaPlayer2',
                'org.freedesktop.DBus.Properties', 'PropertiesChanged',
                GLib.Variant.new_tuple(
                    GLib.Variant('s', interface),
                    GLib.Variant('a{sv}', changed),
                    GLib.Variant('as', invalidated)))
        except GLib.Error as e:
            logging.warning(e)


class MprisPrefsDialog(QDialog):
    """Configure dialog for the MPRIS plugin: a single 'hide on close' toggle,
    stored in the plugin's ``data`` GSetting as 'True'/'False'."""

    def __init__(self, window, settings):
        super().__init__(window)
        self.settings = settings
        self.setWindowTitle(_('MPRIS'))
        self.setModal(True)

        self.check = QCheckBox(_('Hide Pyrrha on close (instead of quitting)'))
        self.check.setChecked(settings['data'] == 'True')
        self.check.toggled.connect(
            lambda on: self.settings.set_string('data', 'True' if on else 'False'))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.hide)
        buttons.accepted.connect(self.hide)

        layout = QVBoxLayout(self)
        layout.addWidget(self.check)
        layout.addWidget(buttons)
