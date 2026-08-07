# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Loader for classic Winamp 2 skins (a .wsz ZIP of BMP sprite sheets, or an
unpacked directory of the same)."""

import logging
import os
import zipfile

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPolygon, QRegion


def _ints(s):
    """Parse a comma/semicolon/space separated list of integers, tolerantly."""
    out = []
    for tok in s.replace(';', ',').replace(' ', ',').split(','):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            try:
                out.append(int(float(tok)))
            except ValueError:
                pass
    return out


class Skin:
    """Loads a skin and hands out sprite regions from its BMP sheets.

    Accepts either a ``.wsz`` file or a directory of loose skin files. Winamp
    skins are inconsistent about filename case, so lookups are case-insensitive
    on the basename (e.g. ``main.bmp`` matches ``MAIN.BMP``).
    """

    def __init__(self, path):
        self.path = path
        self._raw = {}       # basename.lower() -> bytes (BMPs)
        self._text = {}      # basename.lower() -> str (config .txt)
        self._images = {}
        self._regions = None       # region.txt polygons, parsed lazily
        self._region_cache = {}    # (section, scale) -> QRegion

        if os.path.isdir(path):
            for fn in os.listdir(path):
                full = os.path.join(path, fn)
                if os.path.isfile(full):
                    self._store(fn, lambda f=full: open(f, 'rb').read())
        else:
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    if not info.is_dir():
                        self._store(info.filename, lambda i=info: z.read(i))
        logging.info('Loaded skin %s (%d bitmaps, %d text files)',
                     path, len(self._raw), len(self._text))

    def _store(self, name, read):
        base = name.replace('\\', '/').rsplit('/', 1)[-1].lower()
        if base.endswith('.bmp'):
            self._raw[base] = read()
        elif base.endswith('.txt'):
            self._text[base] = read().decode('latin-1', 'replace')

    def has(self, name):
        return name.lower() in self._raw

    def text(self, name):
        """The contents of a config text file (e.g. ``pledit.txt``), or ''."""
        return self._text.get(name.lower(), '')

    def image(self, name):
        name = name.lower()
        if name not in self._images:
            data = self._raw.get(name)
            img = self._decode(data)
            if img.isNull() and data:
                logging.warning('Failed to decode skin bitmap %s', name)
            self._images[name] = img
        return self._images[name]

    @staticmethod
    def _decode(data):
        """Decode skin-bitmap bytes tolerantly. Real skins aren't always clean
        BMPs: some save a PNG/GIF under a .bmp name, others ship BMP variants
        Qt's loader rejects. Try Qt's format sniffing first (which also catches
        the renamed formats), then an explicit BMP hint, then a Pillow fallback
        (if installed) that copes with the odd headers Qt won't."""
        if not data:
            return QImage()
        img = QImage()
        if img.loadFromData(data) or img.loadFromData(data, 'BMP'):
            return img
        return Skin._pillow_decode(data)

    @staticmethod
    def _pillow_decode(data):
        try:
            import io
            from PIL import Image
        except Exception:
            return QImage()
        try:
            pim = Image.open(io.BytesIO(data)).convert('RGBA')
        except Exception:
            return QImage()
        w, h = pim.size
        # Detach from the transient buffer with copy(); RGBA8888 matches PIL's
        # 'raw' RGBA byte order.
        return QImage(pim.tobytes('raw', 'RGBA'), w, h, QImage.Format_RGBA8888).copy()

    def sprite(self, name, x, y, w, h):
        """A w×h QImage cut from bitmap ``name`` at (x, y); empty if missing."""
        img = self.image(name)
        if img.isNull():
            return QImage()
        return img.copy(x, y, w, h)

    # ------------------------------------------------------------ region.txt
    def _parse_regions(self):
        """Parse region.txt into {section: [polygon, ...]} where each polygon is
        a list of (x, y) points at native size. region.txt masks non-rectangular
        skins; sections are Normal / WindowShade / Equalizer / EqualizerWS, each
        with NumPoints (points-per-polygon) and a flat PointList of x,y pairs."""
        self._regions = {}
        text = self.text('region.txt')
        if not text:
            return
        raw = {}   # section -> {'numpoints': str, 'pointlist': str}
        cur = None
        for line in text.splitlines():
            line = line.strip()
            if not line or line[0] in ';#':
                continue
            if line.startswith('[') and line.endswith(']'):
                cur = line[1:-1].strip().lower()
                raw.setdefault(cur, {'numpoints': '', 'pointlist': ''})
            elif cur is not None and '=' in line:
                key, val = line.split('=', 1)
                key = key.strip().lower()
                if key in ('numpoints', 'pointlist'):
                    raw[cur][key] += (',' if raw[cur][key] else '') + val
        for sec, d in raw.items():
            counts = _ints(d['numpoints'])
            coords = _ints(d['pointlist'])
            pts = [(coords[i], coords[i + 1]) for i in range(0, len(coords) - 1, 2)]
            polys, idx = [], 0
            for c in (counts or [len(pts)]):
                poly = pts[idx:idx + c]
                idx += c
                if len(poly) >= 3:
                    polys.append(poly)
            if polys:
                self._regions[sec] = polys

    def region(self, section, scale=1.0):
        """A QRegion for a window state ('normal', 'windowshade', 'equalizer',
        'equalizerws') from region.txt, scaled to the given UI scale; or None if
        this skin defines no region for that state (i.e. it is rectangular)."""
        if self._regions is None:
            self._parse_regions()
        section = section.lower()
        polys = self._regions.get(section)
        if not polys:
            return None
        key = (section, round(scale, 3))
        cached = self._region_cache.get(key)
        if cached is not None:
            return cached
        reg = QRegion()
        for poly in polys:
            qp = QPolygon([QPoint(round(x * scale), round(y * scale)) for x, y in poly])
            reg = reg.united(QRegion(qp))
        reg = reg if not reg.isEmpty() else None
        self._region_cache[key] = reg
        return reg
