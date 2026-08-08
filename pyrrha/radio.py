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

# ICY StreamTitle parsing. Station promos usually carry a domain or a URL; that
# is the most reliable signal, backed up by the station's own name appearing in
# a segment.
_DOMAIN_RE = re.compile(
    r'\b[\w-]+\.(?:com|net|org|fm|radio|live|io|co|tv|stream|app|de|uk|us|ca|nl|ru|fr|es)\b',
    re.IGNORECASE)


def _looks_like_promo(segment, station_name):
    low = segment.lower()
    if 'http://' in low or 'https://' in low or 'www.' in low:
        return True
    if _DOMAIN_RE.search(segment):
        return True
    # The station name (or a distinctive multi-word prefix of it) showing up in
    # a segment is a station ident, not a track.
    name = (station_name or '').strip().lower()
    if len(name) >= 6 and name in low:
        return True
    words = [w for w in re.split(r'\W+', name) if w]
    if len(words) >= 2 and ' '.join(words[:2]) in low:
        return True
    return False


def _strip_promo_clause(segment):
    """Cut a trailing ``" on <host-with-domain>"`` promo (matching the *last*
    ``on`` so real titles like "Dancing on the Ceiling" survive)."""
    m = re.match(r'^(.*)\s+on\s+(\S.*)$', segment, re.IGNORECASE)
    if m and _DOMAIN_RE.search(m.group(2)):
        return m.group(1).strip()
    return segment


def parse_stream_title(streamtitle, station_name=''):
    """Parse an ICY ``StreamTitle`` into ``(artist, title)`` (artist may be None
    when unknown), or None if there's nothing usable. Strips trailing/leading
    station-promo segments and understands ``"Title by Artist"`` in addition to
    ``"Artist - Title"``."""
    streamtitle = (streamtitle or '').strip()
    if not streamtitle:
        return None
    segments = [s.strip() for s in re.split(r'\s+-\s+', streamtitle) if s.strip()]
    if not segments:
        return None
    # Drop promo segments from the ends, always keeping at least one.
    while len(segments) > 1 and _looks_like_promo(segments[-1], station_name):
        segments.pop()
    while len(segments) > 1 and _looks_like_promo(segments[0], station_name):
        segments.pop(0)
    segments[-1] = _strip_promo_clause(segments[-1]) or segments[-1]

    if len(segments) == 1:
        seg = segments[0]
        # "Title by Artist" — only when there's no dash structure to rely on.
        m = re.match(r'^(.+?)\s+by\s+(.+)$', seg, re.IGNORECASE)
        if m and m.group(1).strip() and m.group(2).strip():
            return m.group(2).strip(), m.group(1).strip()   # (artist, title)
        return None, seg                                    # title only
    return segments[0], ' - '.join(segments[1:])            # (artist, title)


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
        """Apply an ICY ``StreamTitle``. Handles the common ``"Artist - Title"``
        as well as ``"Title by Artist"``, and strips trailing station-promo
        segments (``"… - Station on example.com"``). Returns True if the
        displayed artist/title changed."""
        parsed = parse_stream_title(streamtitle, self.name)
        if parsed is None:
            return False
        new_artist, new_title = parsed
        new_artist = new_artist or self.name   # keep both fields populated
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


# -- default stations ------------------------------------------------------

# A small curated set seeded into the favourites on first run so the feature
# isn't empty out of the box. SomaFM's listener-supported streams are stable,
# publicly streamable direct MP3 URLs (no playlist to unwrap).
_DEFAULT_STATIONS = (
    # (name, stream URL, genre tags, homepage)
    ('SomaFM: Groove Salad', 'https://ice1.somafm.com/groovesalad-128-mp3',
     'ambient,downtempo', 'https://somafm.com/groovesalad/'),
    ('SomaFM: Drone Zone', 'https://ice1.somafm.com/dronezone-128-mp3',
     'ambient,space', 'https://somafm.com/dronezone/'),
    ('SomaFM: Indie Pop Rocks!', 'https://ice1.somafm.com/indiepop-128-mp3',
     'indie,pop', 'https://somafm.com/indiepop/'),
    ('SomaFM: Lush', 'https://ice1.somafm.com/lush-128-mp3',
     'chillout,vocal', 'https://somafm.com/lush/'),
    ('SomaFM: Secret Agent', 'https://ice1.somafm.com/secretagent-128-mp3',
     'lounge,downtempo', 'https://somafm.com/secretagent/'),
    ('SomaFM: DEF CON Radio', 'https://ice1.somafm.com/defcon-128-mp3',
     'electronic', 'https://somafm.com/defcon/'),
)


def default_stations():
    """Fresh :class:`RadioStation` objects for the built-in default stations."""
    return [RadioStation(name, url, tags=tags, bitrate=128, homepage=homepage)
            for (name, url, tags, homepage) in _DEFAULT_STATIONS]


def restore_defaults():
    """Add any missing built-in default stations to the favourites (keeping the
    user's own and their order), persist, and return the resulting list."""
    favorites = load_favorites()
    have = {s.audioUrl for s in favorites}
    favorites.extend(s for s in default_stations() if s.audioUrl not in have)
    save_favorites(favorites)
    return favorites


# -- favourites persistence ------------------------------------------------

def _favorites_file():
    d = os.path.join(GLib.get_user_config_dir(), 'pyrrha')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'radio_favorites.json')


def load_favorites():
    """Return the saved favourite stations as :class:`RadioStation` objects.
    On first run (no favourites file yet) the built-in defaults are seeded and
    returned; a file that exists but is empty stays empty (the user cleared it)."""
    try:
        with open(_favorites_file(), encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        seeded = default_stations()
        save_favorites(seeded)
        return seeded
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
