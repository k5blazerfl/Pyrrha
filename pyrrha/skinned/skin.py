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

from PySide6.QtGui import QImage


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
            img = QImage()
            data = self._raw.get(name)
            if data:
                if not img.loadFromData(data, 'BMP'):
                    logging.warning('Failed to decode skin bitmap %s', name)
            self._images[name] = img
        return self._images[name]

    def sprite(self, name, x, y, w, h):
        """A w×h QImage cut from bitmap ``name`` at (x, y); empty if missing."""
        img = self.image(name)
        if img.isNull():
            return QImage()
        return img.copy(x, y, w, h)
