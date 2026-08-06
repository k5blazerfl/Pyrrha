# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""The classic Winamp playlist window (prototype), showing the current station's
song queue.

Renders the title bar from PLEDIT.BMP and the song list in the skin's PLEDIT.TXT
colors (Normal / Current / NormalBG). Each row is "N. Artist - Title" with a
rating marker (love/ban/tired). Double-clicking a song that's ahead of the
current one starts it (Pandora can't go back).

This is the resizable panel (as in Winamp): dragging its bottom-right corner
changes the playlist's width and height, and the shell grows to fit. The main
and EQ panels keep their fixed native size. The optional overall UI scale (Size
menu) multiplies everything on top.
"""

import re

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QMenu, QWidget

W, H = 275, 200                  # default logical size
TITLE_H = 20
ROW_H = 12
LIST_TOP = TITLE_H + 2
GRIP = 14                        # resize-corner hit/indicator size (bottom-right)
HMIN, HMAX = TITLE_H + 3 * ROW_H, 1400   # the playlist resizes vertically only

# Classic PLEDIT frame (borders + bottom button bar + scrollbar), drawn in
# Classic mode for skins that ship it. Sprite coords are the Winamp standard.
FRAME_L, FRAME_R, FRAME_B = 12, 19, 38   # left / right / bottom insets
SB_THUMB = (52, 53, 8, 18)               # scrollbar thumb sprite


def _fmt_time(secs):
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return '%d:%02d:%02d' % (h, m, s) if h else '%d:%02d' % (m, s)

DEFAULTS = {
    'normal': '#00FF00', 'current': '#FFFFFF',
    'normalbg': '#000000', 'selectedbg': '#0000C6',
}
RATING_MARK = {'love': ' ♥', 'ban': ' ⊘', 'tired': ' ⤳'}


def _color(spec, fallback):
    spec = (spec or '').strip()
    if spec and not spec.startswith('#'):
        spec = '#' + spec
    c = QColor(spec)
    return c if c.isValid() else QColor(fallback)


class SkinnedPlaylistWindow(QWidget):
    def __init__(self, controller, skin, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint if parent is None else Qt.Widget)
        self.ctl = controller
        self.skin = skin
        self.setWindowTitle('Pyrrha Playlist')

        colors = self._parse_pledit(skin.text('pledit.txt'))
        self.c_normal = _color(colors.get('normal'), DEFAULTS['normal'])
        self.c_current = _color(colors.get('current'), DEFAULTS['current'])
        self.c_bg = _color(colors.get('normalbg'), DEFAULTS['normalbg'])
        self.c_sel = _color(colors.get('selectedbg'), DEFAULTS['selectedbg'])

        self._font = QFont('monospace')
        self._font.setPixelSize(9)
        self._collapsed = False
        self._closed = False
        self._resizing = False
        self._height = H          # logical height (resizable); width is never dragged

        controller.song_changed.connect(lambda *_: self.update())
        # Repaint on any model change — additions (songs_added covers the
        # asynchronous Pandora fill) and, crucially, clears/resets (e.g.
        # switching to Local Playback empties the list).
        controller.songs_added.connect(lambda *_: self.update())
        model = controller.songs_model
        model.rowsInserted.connect(lambda *_: self.update())
        model.rowsRemoved.connect(lambda *_: self.update())
        model.modelReset.connect(lambda *_: self.update())

    def set_skin(self, skin):
        self.skin = skin
        colors = self._parse_pledit(skin.text('pledit.txt'))
        self.c_normal = _color(colors.get('normal'), DEFAULTS['normal'])
        self.c_current = _color(colors.get('current'), DEFAULTS['current'])
        self.c_bg = _color(colors.get('normalbg'), DEFAULTS['normalbg'])
        self.c_sel = _color(colors.get('selectedbg'), DEFAULTS['selectedbg'])
        self.update()

    # ---------------------------------------------------------- geometry
    def _scale(self):
        return getattr(self.window(), 'scale', 1)

    def _lw(self):
        shell = self.window()
        if getattr(shell, 'mode', 'modern') == 'classic':
            return W                        # classic mode: fixed native width
        return max(W, int(getattr(shell, 'content_w', W)))

    def _lh(self):
        return TITLE_H if self._collapsed else self._height

    def display_width(self):
        return int(self._lw() * self._scale())

    def display_height(self):
        return int(self._lh() * self._scale())

    def _grip_rect(self):
        return QRect(self._lw() - GRIP, self._lh() - GRIP, GRIP, GRIP)

    def _close_rect(self):
        return QRect(self._lw() - 11, 3, 9, 9)

    def _min_rect(self):
        return QRect(self._lw() - 21, 3, 9, 9)

    def _toggle_collapse(self):
        shell = self.window()
        if hasattr(shell, 'toggle_shade'):
            shell.toggle_shade(self)
        else:
            self._collapsed = not self._collapsed
            self.window().relayout()

    def _close_panel(self):
        self._closed = True
        self.hide()
        shell = self.window()
        shell.content_w = W          # restore the default width when closed
        shell.relayout()

    @staticmethod
    def _parse_pledit(text):
        out = {}
        for line in text.splitlines():
            m = re.match(r'\s*(\w+)\s*=\s*(#?[0-9A-Fa-f]{6})', line)
            if m:
                out[m.group(1).lower()] = m.group(2)
        return out

    # ------------------------------------------------------------ helpers
    def _rows(self):
        model = self.ctl.songs_model
        return [model.song_at(i) for i in range(len(model))]

    def _has_frame(self):
        return self.skin.image('pledit.bmp').height() >= 110

    def _frame_on(self):
        return (not self._collapsed
                and getattr(self.window(), 'mode', 'modern') == 'classic'
                and self._has_frame())

    def _visible_range(self, count):
        bottom = FRAME_B if self._frame_on() else 6
        capacity = max(1, (self._lh() - bottom - LIST_TOP) // ROW_H)
        cur = self.ctl.current_song_index or 0
        start = 0
        if count > capacity and cur >= capacity - 1:
            start = min(cur - capacity // 2, count - capacity)
            start = max(0, start)
        return start, min(count, start + capacity)

    # -------------------------------------------------------------- paint
    def paintEvent(self, event):
        w = self._lw()
        p = QPainter(self)
        s = self._scale()
        if s != 1:
            p.scale(s, s)

        lh = self._lh()
        frame = self._frame_on()
        li, ri, bi = (FRAME_L, FRAME_R, FRAME_B) if frame else (0, 0, 0)

        # Body background (inset by the frame borders).
        p.fillRect(QRect(li, TITLE_H, w - li - ri, lh - TITLE_H - bi), self.c_bg)

        # Title bar from PLEDIT.BMP pieces (left corner, tiled fill, right
        # corner, centered title piece), stretched to the current width.
        fill = self.skin.sprite('pledit.bmp', 127, 0, 25, TITLE_H)
        x = 25
        while x < w - 25:
            p.drawImage(x, 0, fill)
            x += 25
        p.drawImage(0, 0, self.skin.sprite('pledit.bmp', 0, 0, 25, TITLE_H))
        p.drawImage(w - 25, 0, self.skin.sprite('pledit.bmp', 153, 0, 25, TITLE_H))
        p.drawImage((w - 100) // 2, 0, self.skin.sprite('pledit.bmp', 26, 0, 100, TITLE_H))

        if self._collapsed:
            p.end()
            return

        # Classic frame: side/bottom borders, bottom button bar and scrollbar.
        if frame:
            self._paint_frame(p, w, lh)

        # Song list (inset within the frame).
        p.setFont(self._font)
        songs = self._rows()
        cur = self.ctl.current_song_index
        start, end = self._visible_range(len(songs))
        y = LIST_TOP
        for i in range(start, end):
            song = songs[i]
            if song is None:
                continue
            row = QRect(li, y, w - li - ri, ROW_H)
            if i == cur:
                p.fillRect(row, self.c_sel)
            mark = RATING_MARK.get(self.ctl.song_icon(song), '')
            text = '{}. {} - {}{}'.format(i + 1, song.artist, song.title, mark)
            p.setPen(self.c_current if i == cur else self.c_normal)
            p.drawText(row.adjusted(4, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
            y += ROW_H

        # Track count + total duration in the bottom bar (Winamp shows time here).
        if frame:
            total = sum(int(s.get_duration_sec() or 0) for s in songs if s is not None)
            label = '{} / {}'.format(len(songs), _fmt_time(total))
            p.setPen(self.c_current)
            p.drawText(QRect(li, lh - FRAME_B, w - li - 30, FRAME_B),
                       Qt.AlignRight | Qt.AlignVCenter, label)

        # Resize grip (only without a frame; the frame has its own handle).
        if not frame:
            p.setPen(self.c_normal)
            bx, by = w - 3, lh - 3
            for d in (3, 6, 9):
                p.drawLine(bx - d, by, bx, by - d)
        p.end()

    def _paint_frame(self, p, w, lh):
        sk = self.skin
        lb = sk.sprite('pledit.bmp', 0, 42, FRAME_L, 29)
        rb = sk.sprite('pledit.bmp', 32, 42, FRAME_R, 29)
        y = TITLE_H
        while y < lh - FRAME_B:
            p.drawImage(0, y, lb)
            p.drawImage(w - FRAME_R, y, rb)
            y += 29
        # Bottom bar: left corner (Add/Rem/Sel/Misc) + tiled fill + right corner.
        by = lh - FRAME_B
        fill = sk.sprite('pledit.bmp', 150, 72, 25, FRAME_B)
        x = 125
        while x < w - 150:
            p.drawImage(x, by, fill)
            x += 25
        p.drawImage(0, by, sk.sprite('pledit.bmp', 0, 72, 125, FRAME_B))
        p.drawImage(w - 150, by, sk.sprite('pledit.bmp', 126, 72, 150, FRAME_B))
        # Scrollbar thumb on the right border.
        count = len(self._rows())
        start, end = self._visible_range(count)
        cap = max(1, end - start)
        track_top = TITLE_H + 1
        track_h = max(0, lh - FRAME_B - track_top - SB_THUMB[3])
        frac = start / (count - cap) if count > cap else 0.0
        ty = track_top + int(frac * track_h)
        p.drawImage(w - FRAME_R + 2, ty, sk.sprite('pledit.bmp', *SB_THUMB))

    # -------------------------------------------------------------- mouse
    def _song_index_at(self, y):
        songs = self._rows()
        start, end = self._visible_range(len(songs))
        row = (y - LIST_TOP) // ROW_H
        idx = start + row
        return idx if start <= idx < end else None

    def mouseDoubleClickEvent(self, event):
        pos = (event.position() / self._scale()).toPoint()
        # Double-click the corner grip: widen the player to expose the album
        # art beside the EQ (or collapse back).
        if (not self._collapsed and getattr(self, '_is_bottom', False)
                and self._grip_rect().contains(pos)):
            self.window().toggle_width()
            return
        idx = self._song_index_at(pos.y())
        cur = self.ctl.current_song_index
        if idx is not None and cur is not None and idx > cur:
            self.ctl.start_song(idx)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = (event.position() / self._scale()).toPoint()
        if (not self._collapsed and getattr(self, '_is_bottom', False)
                and self._grip_rect().contains(pos)):
            self._resizing = True
            return
        if self._close_rect().contains(pos):
            self._close_panel()
            return
        if self._min_rect().contains(pos):
            self._toggle_collapse()
            return
        if pos.y() < TITLE_H:
            shell = self.window()
            # Classic: tear the playlist off the stack (magnetically re-snaps).
            # Modern: drag the whole shell via the compositor.
            if getattr(shell, 'mode', 'modern') == 'classic':
                self._titledrag = True
                shell.start_free_drag(self, event.globalPosition().toPoint())
            else:
                handle = shell.windowHandle()
                if handle is not None:
                    handle.startSystemMove()

    def contextMenuEvent(self, event):
        if self._collapsed:
            return
        s = self._scale()
        ly = int(event.pos().y() / s)
        if ly < TITLE_H:
            return
        idx = self._song_index_at(ly)
        songs = self._rows()
        if idx is None or not (0 <= idx < len(songs)) or songs[idx] is None:
            return
        song = songs[idx]
        c = self.ctl
        icon = c.song_icon(song)
        menu = QMenu(self)
        if icon == 'love':
            menu.addAction(_('Unlove'), lambda: c.unrate_song(song=song))
        else:
            menu.addAction(_('Love'), lambda: c.love_song(song=song))
        if icon == 'ban':
            menu.addAction(_('Unban'), lambda: c.unrate_song(song=song))
        else:
            menu.addAction(_('Ban'), lambda: c.ban_song(song=song))
        menu.addAction(_('Tired (shelve for a month)'), lambda: c.tired_song(song=song))
        menu.addSeparator()
        menu.addAction(_('Create Station from Artist'), lambda: c.create_artist_station(song))
        menu.addAction(_('Create Station from Song'), lambda: c.create_song_station(song))
        menu.exec(event.globalPos())

    def mouseMoveEvent(self, event):
        if getattr(self, '_titledrag', False):
            self.window().free_drag_move(self, event.globalPosition().toPoint())
            return
        if self._resizing:
            # Drag the corner: vertical only. Classic mode stays native width;
            # modern width is driven by the double-click album-art widen.
            s = self._scale()
            tl = self.mapToGlobal(QPoint(0, 0))
            gy = event.globalPosition().toPoint().y()
            new_h = int(max(HMIN, min(HMAX, (gy - tl.y()) / s)))
            shell = self.window()
            if hasattr(shell, 'resize_panel_height'):
                shell.resize_panel_height(self, new_h)
            else:
                self._height = new_h
                self.window().relayout()

    def mouseReleaseEvent(self, event):
        if getattr(self, '_titledrag', False):
            self._titledrag = False
            self.window().end_free_drag()
            return
        self._resizing = False

    def wheelEvent(self, event):
        self.window().wheelEvent(event)   # scroll -> volume
