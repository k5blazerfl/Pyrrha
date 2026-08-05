# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Winamp bitmap fonts: the 5x6 TEXT.BMP font and the 9x13 NUMBERS.BMP digits."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

# TEXT.BMP character map: each cell is 5x6, laid out in rows. Uppercase only
# (Winamp displays titles uppercased). Standard classic layout.
CHAR_W, CHAR_H = 5, 6
_ROWS = [
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ"@ ',
    "0123456789….:()-'!_+\\/[]^&%.=$#",
    "ÅÖÄ?* ",
]


class TextFont:
    def __init__(self, skin):
        self.skin = skin
        self._map = {}
        for row, chars in enumerate(_ROWS):
            for col, ch in enumerate(chars):
                self._map.setdefault(ch, (col * CHAR_W, row * CHAR_H))
        self._blank = self._map.get(' ', (28 * CHAR_W, 0))

    def _cell(self, ch):
        return self._map.get(ch.upper(), self._blank)

    def render(self, text):
        """Render ``text`` to a QImage using the skin's TEXT.BMP."""
        text = text or ''
        width = max(1, len(text) * CHAR_W)
        img = QImage(width, CHAR_H, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        for i, ch in enumerate(text):
            x, y = self._cell(ch)
            p.drawImage(i * CHAR_W, 0, self.skin.sprite('text.bmp', x, y, CHAR_W, CHAR_H))
        p.end()
        return img


# NUMBERS.BMP: digits 0-9, each 9x13, side by side; a blank sits after them.
NUM_W, NUM_H = 9, 13


class NumberFont:
    def __init__(self, skin):
        self.skin = skin
        # Skins ship either numbers.bmp or the extended nums_ex.bmp; digits 0-9
        # sit at x=i*9 in both. Cell 10 is blank; the extended sheet adds "-" at
        # cell 11 (used for the remaining-time display).
        self.bmp = 'numbers.bmp' if skin.has('numbers.bmp') else 'nums_ex.bmp'
        img = skin.image(self.bmp)
        self._cells = (img.width() // NUM_W) if img is not None and not img.isNull() else 11

    def digit(self, ch):
        if ch.isdigit():
            idx = int(ch)
        elif ch == '-' and self._cells >= 12:
            idx = 11
        else:
            idx = 10   # blank cell (spaces / colon gaps / minus fallback)
        return self.skin.sprite(self.bmp, idx * NUM_W, 0, NUM_W, NUM_H)
