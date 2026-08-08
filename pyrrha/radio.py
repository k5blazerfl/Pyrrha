# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Internet-radio playback support.

Like local files, an internet-radio station reuses Pyrrha's Pandora-shaped
``Song`` machinery: :class:`RadioStation` duck-types the slice of the ``Song``
interface the window and models touch (title/artist/album, ``audioUrl``,
ratings, ``is_still_valid`` …). Ratings and bookmarks are no-ops.

Unlike a track, a stream has no length: playback is continuous and the
"now playing" text arrives out-of-band as ICY metadata — a GStreamer
``message::tag`` carrying ``GST_TAG_TITLE`` ("Artist - Title" by convention),
applied via :meth:`RadioStation.set_stream_title` from the window's tag handler.

Favourite stations persist as a small JSON file in the user config dir; station
discovery lives in :mod:`pyrrha.radiobrowser`.
"""

import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

from gi.repository import GLib

from .pandora import RATE_NONE

# Playlist container formats that wrap a stream URL. ``.m3u8`` is deliberately
# excluded: that's HLS, which GStreamer's playbin plays directly.
_PLAYLIST_EXTS = ('.pls', '.m3u', '.asx', '.xspf')


class RadioStation:
    """An Icecast/Shoutcast stream dressed up as a Pandora ``Song`` for the
    player and song list."""

    def __init__(self, name, url, *, uuid=None, favicon=None, tags='',
                 codec='', bitrate=0, homepage='', country=''):
        self.name = name or url
        self.audioUrl = url                 # the stream URL playbin receives
        self.stationuuid = uuid
        self.favicon = favicon or None
        self.station_tags = tags
        self.codec = codec
        self.homepage = homepage
        self.country = country

        # Presentation. title/artist are overwritten by ICY StreamTitle updates
        # once the stream is playing; until then we show the station name.
        self.title = self.name
        self.artist = _('Internet Radio')
        self.album = self.name

        # Song fields the window/models read. A live stream has no length, so
        # duration stays None — query_duration() returns None for it as well,
        # and get_duration_sec() reports 0 (the UI shows a LIVE state).
        self.duration = None            # nanoseconds; unknown for live streams
        self.trackLength = 0            # seconds; duration fallback
        self.trackGain = 0.0            # ReplayGain is meaningless for streams
        self.bitrate = bitrate or None
        self.position = None
        self.start_time = None
        self.duration_message = None
        self.message = ''
        self.tired = False
        self.rating = RATE_NONE
        self.is_ad = False
        self.finished = False
        self.feedbackId = None
        self.index = None
        # Route the station logo through the Pandora album-art fetch path: the
        # window downloads ``artRadio`` on a worker and sets the row pixmap.
        self.artRadio = self.favicon
        self.artUrl = None
        self.art_pixbuf = None
        self.art_bytes = None
        self.songDetailURL = homepage or ''
        # Synthetic ASCII token so consumers that key off it (e.g. the MPRIS
        # plugin's track object paths) work without special-casing.
        self.trackToken = 'radio-' + (uuid or hashlib.sha1(
            url.encode('utf-8')).hexdigest())
        self.playlist_time = 0
        # True until the URL has been checked/unwrapped: a station URL pointing
        # at a .pls/.m3u/.asx playlist must be resolved to the real stream URL
        # before playbin gets it (done lazily on first play, in the window).
        self._needs_resolve = is_playlist_url(url)

    # -- ICY now-playing ---------------------------------------------------
    def set_stream_title(self, streamtitle):
        """Apply an ICY ``StreamTitle`` (conventionally ``"Artist - Title"``).
        Returns True if the displayed artist/title changed."""
        streamtitle = (streamtitle or '').strip()
        if not streamtitle:
            return False
        artist, sep, title = streamtitle.partition(' - ')
        if sep:
            new_artist, new_title = artist.strip(), title.strip()
        else:
            # No separator: many stations send just a title (or the station
            # name). Keep the station name as the artist so scrobbles/MPRIS
            # still have both fields populated.
            new_artist, new_title = self.name, streamtitle
        if (new_artist, new_title) == (self.artist, self.title):
            return False
        self.artist, self.title = new_artist, new_title
        return True

    # -- Song interface the window relies on (all inert for streams) -------
    def is_still_valid(self):
        return True

    def get_duration_sec(self):
        return 0

    def get_position_sec(self):
        return self.position // 1000000000 if self.position else 0

    def rate(self, rating):
        pass

    def set_tired(self):
        pass

    def bookmark(self):
        pass

    def bookmark_artist(self):
        pass

    # -- (de)serialisation for the favourites file -------------------------
    def to_dict(self):
        return {
            'name': self.name, 'url': self.audioUrl, 'uuid': self.stationuuid,
            'favicon': self.favicon, 'tags': self.station_tags,
            'codec': self.codec, 'bitrate': self.bitrate or 0,
            'homepage': self.homepage, 'country': self.country,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            d.get('name', ''), d.get('url', ''), uuid=d.get('uuid'),
            favicon=d.get('favicon'), tags=d.get('tags', ''),
            codec=d.get('codec', ''), bitrate=d.get('bitrate', 0),
            homepage=d.get('homepage', ''), country=d.get('country', ''))

    def __repr__(self):
        return '<RadioStation "{}">'.format(self.name)


# -- favourites persistence ------------------------------------------------

def _favorites_file():
    d = os.path.join(GLib.get_user_config_dir(), 'pyrrha')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'radio_favorites.json')


def load_favorites():
    """Return the saved favourite stations as :class:`RadioStation` objects
    (empty list if none are saved or the file is unreadable)."""
    try:
        with open(_favorites_file(), encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        logging.warning('Could not read radio favourites: %s', e)
        return []
    out = []
    for d in data if isinstance(data, list) else []:
        try:
            if isinstance(d, dict) and d.get('url'):
                out.append(RadioStation.from_dict(d))
        except Exception as e:
            logging.info('Skipping malformed radio favourite: %s', e)
    return out


def save_favorites(stations):
    """Persist the given :class:`RadioStation` objects as the favourites list.
    Returns True on success."""
    try:
        with open(_favorites_file(), 'w', encoding='utf-8') as f:
            json.dump([s.to_dict() for s in stations], f, indent=1)
        return True
    except OSError as e:
        logging.warning('Could not save radio favourites: %s', e)
        return False


# -- stream-URL resolution (.pls / .m3u / .asx / .xspf) --------------------

def is_playlist_url(url):
    """Whether ``url`` points at a playlist container we should unwrap before
    handing it to playbin (not a directly-playable stream)."""
    try:
        return urlsplit(url).path.lower().endswith(_PLAYLIST_EXTS)
    except Exception:
        return False


def resolve_stream_url(url, proxy=None):
    """Return a directly-playable stream URL for ``url``. If it points at a
    playlist file, fetch and parse it and return the first HTTP(S) entry;
    otherwise (or on any error) return ``url`` unchanged. Blocking — run on a
    worker thread."""
    if not is_playlist_url(url):
        return url
    try:
        text = _fetch_text(url, proxy)
    except (urllib.error.URLError, OSError, ValueError) as e:
        logging.info('Could not fetch playlist %s: %s', url, e)
        return url
    for candidate in _parse_playlist(text, url):
        return candidate
    return url


def _fetch_text(url, proxy=None, timeout=8, max_bytes=64 * 1024):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))
    req = urllib.request.Request(url, headers={'User-Agent': 'Pyrrha'})
    with urllib.request.build_opener(*handlers).open(req, timeout=timeout) as r:
        return r.read(max_bytes).decode('utf-8', 'replace')


def _parse_playlist(text, base):
    """Extract candidate stream URLs from PLS / M3U / ASX / XSPF text, resolving
    relative entries against ``base`` and keeping only HTTP(S) URLs."""
    low = text.lstrip().lower()
    raw = []
    if low.startswith('[playlist]') or re.search(r'(?im)^\s*file\d*\s*=', text):
        raw = [m.group(1).strip()
               for m in re.finditer(r'(?im)^\s*File\d*\s*=\s*(\S+)', text)]
    elif '<asx' in low or '<ref' in low:
        raw = [m.group(1).strip() for m in re.finditer(
            r'(?is)<ref\s+href\s*=\s*["\']([^"\']+)["\']', text)]
    elif '<playlist' in low or '<location>' in low:      # XSPF
        raw = [m.group(1).strip() for m in re.finditer(
            r'(?is)<location>\s*([^<]+?)\s*</location>', text)]
    else:                                                 # M3U: bare URL lines
        raw = [line.strip() for line in text.splitlines()
               if line.strip() and not line.strip().startswith('#')]
    out = []
    for entry in raw:
        resolved = urljoin(base, entry)
        if urlsplit(resolved).scheme in ('http', 'https'):
            out.append(resolved)
    return out
