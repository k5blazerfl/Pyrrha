# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Local-file playback support (Tier 1 prototype).

Pyrrha's player and song list are built around Pandora's ``Song`` object. To
reuse that machinery for local audio files we provide :class:`LocalSong`, which
duck-types the slice of the ``Song`` interface the window and models touch
(title/artist/album, ``audioUrl``, ratings, ``is_still_valid`` …). Ratings,
bookmarks and "tired" are no-ops for local files.

Metadata (tags, duration, embedded cover art) is read with GStreamer's
``GstPbutils.Discoverer`` — no extra dependency, since GStreamer is already
required. Discovery is synchronous; fine for the handful-of-files prototype.
"""

import hashlib
import logging
import os

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstPbutils', '1.0')
from gi.repository import Gst, GstPbutils, GLib

from .pandora import RATE_NONE

# Audio extensions we offer to open. GStreamer decodes far more; this list just
# drives the file dialog filter and the folder scan.
AUDIO_EXTENSIONS = (
    '.mp3', '.flac', '.ogg', '.oga', '.opus', '.m4a', '.aac', '.wav', '.wave',
    '.wma', '.ape', '.aiff', '.aif', '.alac', '.wv', '.spx',
)

_discoverer = None


def _get_discoverer():
    global _discoverer
    if _discoverer is None:
        Gst.init(None)
        _discoverer = GstPbutils.Discoverer.new(5 * Gst.SECOND)
    return _discoverer


def _tag_str(tags, name):
    if tags is None:
        return None
    ok, val = tags.get_string(name)
    return val if ok and val else None


def _tag_image(tags):
    """Bytes of an embedded cover image, or None."""
    if tags is None:
        return None
    for tag in (Gst.TAG_IMAGE, Gst.TAG_PREVIEW_IMAGE):
        ok, sample = tags.get_sample_index(tag, 0)
        if not ok or sample is None:
            continue
        buf = sample.get_buffer()
        if buf is None:
            continue
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            continue
        try:
            return bytes(mapinfo.data)
        finally:
            buf.unmap(mapinfo)
    return None


def _sidecar_art(path):
    """Bytes of a cover image sitting next to the file (cover.jpg, folder.png…)."""
    d = os.path.dirname(path)
    for name in ('cover.jpg', 'cover.jpeg', 'cover.png', 'folder.jpg',
                 'folder.png', 'front.jpg', 'album.jpg'):
        for cand in (name, name.upper(), name.capitalize()):
            p = os.path.join(d, cand)
            if os.path.isfile(p):
                try:
                    with open(p, 'rb') as f:
                        return f.read()
                except OSError:
                    pass
    return None


class LocalSong:
    """A local audio file dressed up as a Pandora ``Song`` for the player/UI."""

    def __init__(self, path):
        self.path = path
        self.audioUrl = Gst.filename_to_uri(os.path.abspath(path))

        # Presentation defaults, overwritten by tags below.
        base = os.path.splitext(os.path.basename(path))[0]
        self.title = base
        self.artist = 'Unknown Artist'
        self.album = 'Local Files'
        self.art_bytes = None
        self.duration = None            # nanoseconds (set from tags if known)

        self._read_metadata()
        # Pandora Song field, in seconds; the gst stream-start handler uses it
        # as a duration fallback and compares against the queried duration.
        self.trackLength = self.get_duration_sec()

        # Fields the window/models read on a Song. Kept inert for local files.
        self.trackGain = 0.0            # ReplayGain track gain (dB); set by a scan
        self.bitrate = None
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
        self.artRadio = None            # no remote art URL; we set the pixmap directly
        self.artUrl = None
        self.art_pixbuf = None
        # Pandora-only identifiers. songDetailURL is empty (no web page); the
        # trackToken is a synthetic ASCII id so consumers that key off it (e.g.
        # the MPRIS plugin's track object paths) work without special-casing.
        self.songDetailURL = ''
        self.trackToken = 'local-' + hashlib.sha1(
            os.path.abspath(path).encode('utf-8')).hexdigest()
        self.playlist_time = 0

    def _read_metadata(self):
        try:
            info = _get_discoverer().discover_uri(self.audioUrl)
        except GLib.Error as e:
            logging.info('Could not read tags for %s: %s', self.path, e)
            info = None

        tags = info.get_tags() if info is not None else None
        self.title = _tag_str(tags, Gst.TAG_TITLE) or self.title
        self.artist = _tag_str(tags, Gst.TAG_ARTIST) or self.artist
        self.album = _tag_str(tags, Gst.TAG_ALBUM) or self.album
        self.art_bytes = _tag_image(tags) or _sidecar_art(self.path)

        if info is not None:
            dur = info.get_duration()   # ns, 0 if unknown
            if dur:
                self.duration = dur

    # -- Song interface the window relies on (all inert for local files) ----
    def is_still_valid(self):
        return True

    def get_duration_sec(self):
        return self.duration // 1000000000 if self.duration else 0

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

    def __repr__(self):
        return '<LocalSong "{}" by "{}">'.format(self.title, self.artist)


# -- tag editing (optional; needs mutagen) ---------------------------------

try:
    import mutagen
except ImportError:
    mutagen = None

# Editable fields, in display order, via mutagen's Easy interface (portable
# across MP3/FLAC/Ogg/MP4).
TAG_KEYS = ('title', 'artist', 'album', 'albumartist', 'tracknumber',
            'genre', 'date', 'comment')


def tags_editable():
    """Whether tag editing is available (mutagen installed)."""
    return mutagen is not None


def read_tags(path):
    """Current editable tags as {key: str}, or None if the format has no tag
    support (or mutagen is missing)."""
    if mutagen is None:
        return None
    try:
        f = mutagen.File(path, easy=True)
    except Exception as e:
        logging.info('Could not read tags for %s: %s', path, e)
        return None
    if f is None:
        return None
    out = {}
    for k in TAG_KEYS:
        v = f.get(k)
        out[k] = v[0] if isinstance(v, list) and v else (v or '')
    return out


def write_tags(path, values):
    """Write {key: str} tags with mutagen (empty values delete the tag).
    Returns True on success."""
    if mutagen is None:
        return False
    try:
        f = mutagen.File(path, easy=True)
        if f is None:
            return False
        for k, v in values.items():
            if v:
                f[k] = [v]
            elif k in f:
                del f[k]
        f.save()
        return True
    except Exception as e:
        logging.warning('Failed to write tags for %s: %s', path, e)
        return False


# -- ReplayGain scanning (rganalysis) --------------------------------------

def scan_replaygain(paths, progress=None):
    """Compute ReplayGain track gain (dB) for each path via GStreamer's
    ``rganalysis``. Returns {path: gain_db} for those that scanned. ``progress``
    (if given) is called as ``progress(done, total)``. Runs synchronously — call
    it from a worker thread."""
    result = {}
    total = len(paths)
    for i, path in enumerate(paths):
        gain = _scan_one_replaygain(path)
        if gain is not None:
            result[path] = gain
        if progress is not None:
            progress(i + 1, total)
    return result


def _scan_one_replaygain(path):
    src = Gst.ElementFactory.make('uridecodebin', None)
    conv = Gst.ElementFactory.make('audioconvert', None)
    resample = Gst.ElementFactory.make('audioresample', None)
    rg = Gst.ElementFactory.make('rganalysis', None)
    sink = Gst.ElementFactory.make('fakesink', None)
    if not all((src, conv, resample, rg, sink)):
        return None
    pipe = Gst.Pipeline.new('rgscan')
    src.set_property('uri', Gst.filename_to_uri(os.path.abspath(path)))
    rg.set_property('num-tracks', 1)
    for el in (src, conv, resample, rg, sink):
        pipe.add(el)
    conv.link(resample)
    resample.link(rg)
    rg.link(sink)

    def _on_pad(_el, pad):
        sinkpad = conv.get_static_pad('sink')
        if not sinkpad.is_linked():
            pad.link(sinkpad)
    src.connect('pad-added', _on_pad)

    pipe.set_state(Gst.State.PLAYING)
    bus = pipe.get_bus()
    want = Gst.MessageType.TAG | Gst.MessageType.EOS | Gst.MessageType.ERROR
    gain = None
    while True:
        msg = bus.timed_pop_filtered(30 * Gst.SECOND, want)
        if msg is None:
            break
        if msg.type == Gst.MessageType.TAG:
            ok, g = msg.parse_tag().get_double(Gst.TAG_TRACK_GAIN)
            if ok:
                gain = g
        else:                       # EOS or ERROR
            break
    pipe.set_state(Gst.State.NULL)
    return gain


def collect_audio_files(paths):
    """Expand a mix of files and directories into a sorted list of audio files."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for name in sorted(files):
                    if name.lower().endswith(AUDIO_EXTENSIONS):
                        out.append(os.path.join(root, name))
        elif os.path.isfile(p) and p.lower().endswith(AUDIO_EXTENSIONS):
            out.append(p)
    return out


def build_songs(paths):
    """Build LocalSong objects for the given audio file paths."""
    songs = []
    for path in paths:
        try:
            songs.append(LocalSong(path))
        except Exception as e:
            logging.warning('Skipping %s: %s', path, e)
    return songs


# -- playlist files (M3U / PLS) --------------------------------------------

PLAYLIST_EXTENSIONS = ('.m3u', '.m3u8', '.pls')


def write_m3u(path, songs):
    """Write an extended-M3U playlist for the given LocalSong objects. Paths are
    stored relative to the playlist when they live under its directory (more
    portable), else absolute."""
    base = os.path.dirname(os.path.abspath(path))
    lines = ['#EXTM3U']
    for s in songs:
        sp = os.path.abspath(s.path)
        rel = os.path.relpath(sp, base)
        stored = sp if rel.startswith('..') else rel
        lines.append('#EXTINF:{},{} - {}'.format(
            s.get_duration_sec() or -1, s.artist, s.title))
        lines.append(stored)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def _resolve(base, entry):
    p = entry if os.path.isabs(entry) else os.path.join(base, entry)
    p = os.path.abspath(p)
    return p if os.path.isfile(p) else None


def read_playlist(path):
    """Return the ordered, existing file paths referenced by an M3U or PLS
    playlist. Relative entries resolve against the playlist's directory."""
    base = os.path.dirname(os.path.abspath(path))
    is_pls = path.lower().endswith('.pls')
    out = []
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if is_pls:
                    if line.lower().startswith('file'):
                        entry = line.partition('=')[2].strip()
                    else:
                        continue
                elif line.startswith('#'):
                    continue
                else:
                    entry = line
                resolved = _resolve(base, entry)
                if resolved:
                    out.append(resolved)
    except OSError as e:
        logging.warning('Could not read playlist %s: %s', path, e)
    return out
