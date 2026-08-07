# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget,
)

from ..appicon import app_icon

# Scrolling credits (à la the classic Winamp About box). ``kind`` styles the
# line: 'title' bright/bold, 'head' an accent heading, None a normal line. The
# trailing blanks leave a gap before the loop wraps.
CREDITS = [
    ('Pyrrha', 'title'),
    ('', None),
    ('A Qt / PySide6 port of Pithos,', None),
    ('the native Pandora Radio client', None),
    ('', None),
    ('Port & skinned Winamp UI', 'head'),
    ('k5blazerfl', None),
    ('', None),
    ('Built upon', 'head'),
    ('Pithos and its contributors', None),
    ('', None),
    ('Classic look inspired by', 'head'),
    ('Winamp 2.x and its skin format', None),
    ('', None),
    ("It really burns the llama's ass!", None),
    ('', None),
    ('Not affiliated with Pandora Media,', None),
    ('Nullsoft, or Winamp', None),
    ('', None),
    ('', None),
    ('', None),
]


class CreditsScroller(QWidget):
    """A dark panel whose credit lines scroll upward and loop seamlessly."""

    BG = QColor('#0a0f0a')
    C_NORMAL = QColor('#3fce3f')
    C_HEAD = QColor('#9fe6ff')
    C_TITLE = QColor('#ffffff')

    def __init__(self, lines, parent=None):
        super().__init__(parent)
        self._lines = lines
        self.setFixedSize(320, 150)
        self._font = QFont()
        self._font.setPixelSize(12)
        self._title_font = QFont(self._font)
        self._title_font.setPixelSize(16)
        self._title_font.setBold(True)
        self._line_h = QFontMetrics(self._font).height() + 4
        self._total = max(1, len(lines) * self._line_h)
        self._offset = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)   # ~33 fps

    def _tick(self):
        self._offset = (self._offset + 1) % self._total
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self.BG)
        w, h, lh = self.width(), self.height(), self._line_h
        for i, (text, kind) in enumerate(self._lines):
            if not text:
                continue
            # Position each line on the looping tape and skip the off-screen ones.
            y = h - ((self._offset - i * lh) % self._total)
            if y < -lh or y > h:
                continue
            if kind == 'title':
                p.setFont(self._title_font)
                p.setPen(self.C_TITLE)
            else:
                p.setFont(self._font)
                p.setPen(self.C_HEAD if kind == 'head' else self.C_NORMAL)
            p.drawText(0, int(y), w, lh, Qt.AlignHCenter | Qt.AlignVCenter, text)
        p.end()


class AboutDialog(QDialog):
    def __init__(self, version, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('About Pyrrha'))
        self.setModal(True)

        layout = QVBoxLayout(self)

        icon = app_icon()
        if not icon.isNull():
            logo = QLabel()
            logo.setPixmap(icon.pixmap(96, 96))
            logo.setAlignment(Qt.AlignCenter)
            layout.addWidget(logo)

        title = QLabel('<h2>Pyrrha</h2>')
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        scroller = CreditsScroller(CREDITS)
        wrap = QVBoxLayout()
        wrap.addWidget(scroller, alignment=Qt.AlignCenter)
        layout.addLayout(wrap)

        body = QLabel(
            _('Version') + ' ' + version +
            '<br><br>' + _('Pyrrha is not affiliated with or endorsed by Pandora Media, Inc.') +
            '<br><a href="https://github.com/k5blazerfl/Pyrrha">github.com/k5blazerfl/Pyrrha</a>'
        )
        body.setAlignment(Qt.AlignCenter)
        body.setOpenExternalLinks(True)
        body.setTextFormat(Qt.RichText)
        layout.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
