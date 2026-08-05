# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""The classic Winamp equalizer window (prototype), wired to Pyrrha's real
10-band GStreamer equalizer element.

Renders EQMAIN.BMP: the 10 band sliders (+ a preamp slider), an ON toggle and
the response-curve graph. Dragging a band slider drives
``controller.equalizer`` (the ``equalizer-10bands`` element) live; the ON toggle
flattens/restores it. Sliders are mapped ±12 dB (middle = 0 dB), within the
element's -24..+12 range. Slider-column and button offsets follow the classic
EQMAIN spec and are easy to tune against a real skin.
"""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget

W, H = 275, 116
BANDS = 10

TITLE_H = 14
THUMB_W, THUMB_H = 11, 11
SLIDER_TOP = 38
SLIDER_TRAVEL = 51          # vertical thumb travel (px)
PREAMP_X = 21
BAND_X0, BAND_DX = 78, 18   # band columns: 78, 96, ... 240 (spread out when wider)
GRAPH = QRect(86, 17, 113, 19)
ON_BTN = QRect(14, 18, 25, 12)
PRESETS_BTN = QRect(214, 18, 50, 12)   # opens the preset menu
MIN_BTN = QRect(254, 3, 9, 9)     # windowshade: collapse to the title bar
CLOSE_BTN = QRect(264, 3, 9, 9)   # close (hide) the panel

DB_RANGE = 12.0             # slider maps +/- this many dB (middle = 0)
DB_MIN, DB_MAX = -24.0, 12.0  # element's actual limits

# Classic 10-band EQ presets (dB per band, low → high frequency).
PRESETS = [
    ('Flat',              [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    ('Rock',              [8, 5, -4, -7, -3, 3, 7, 10, 11, 11]),
    ('Pop',               [-1, 4, 7, 8, 5, 0, -2, -2, -1, -1]),
    ('Jazz',              [4, 3, 1, 2, -2, -2, 0, 1, 3, 4]),
    ('Classical',         [0, 0, 0, 0, 0, 0, -6, -6, -6, -8]),
    ('Dance',             [7, 5, 2, 0, 0, -4, -6, -6, 0, 0]),
    ('Electronic',        [5, 4, 1, 0, -2, 2, 1, 1, 5, 6]),
    ('Hip-Hop',           [6, 5, 2, 3, -1, -1, 1, -1, 2, 3]),
    ('Vocal',             [-2, -3, -3, 1, 4, 4, 3, 1, 0, -2]),
    ('Bass Boost',        [8, 7, 6, 4, 1, 0, 0, 0, 0, 0]),
    ('Treble Boost',      [0, 0, 0, 0, 0, 1, 3, 5, 7, 8]),
    ('Loudness',          [7, 5, 0, 0, -3, 0, -1, -6, 6, 1]),
]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


class SkinnedEqWindow(QWidget):
    def __init__(self, controller, skin, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint if parent is None else Qt.Widget)
        self.ctl = controller
        self.skin = skin
        self.eq = controller.equalizer
        self.setFixedSize(W, H)
        self.setWindowTitle('Pyrrha EQ')

        self._on = True
        self._preamp = 0.0
        self._bands = [float(self.eq.get_property('band%d' % i)) for i in range(BANDS)]
        self._drag = None   # index of slider being dragged (-1 = preamp)
        self._collapsed = False
        self._closed = False

        # Repaint the album art when the song or its artwork changes.
        controller.song_changed.connect(lambda *_: self.update())
        controller.metadata_changed.connect(lambda *_: self.update())
        # Restore each station's remembered EQ when it becomes active.
        controller.station_changed_sig.connect(self._on_station_changed)

    def set_skin(self, skin):
        self.skin = skin
        self.update()

    def _scale(self):
        return getattr(self.window(), 'scale', 1)

    def _lw(self):
        return max(W, int(getattr(self.window(), 'content_w', W)))

    def display_width(self):
        # The EQ face itself can't stretch (its sliders, graph box, labels and
        # preset bar are baked in), so it stays native at the left; the panel
        # spans the full width and shows the album art in the area to its right.
        return int(self._lw() * self._scale())

    def display_height(self):
        return int((TITLE_H if self._collapsed else H) * self._scale())

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self.window().relayout()

    def _close_panel(self):
        self._closed = True
        self.hide()
        self.window().relayout()

    # ----------------------------------------------------------- geometry
    def _col_x(self, i):
        # The sliders, graph box and frequency labels are baked into the skin
        # at fixed positions, so they stay native; only the panel widens.
        return PREAMP_X if i == -1 else BAND_X0 + i * BAND_DX

    def _value_to_y(self, db):
        f = _clamp((DB_RANGE - db) / (2 * DB_RANGE), 0.0, 1.0)
        return SLIDER_TOP + int(round(f * SLIDER_TRAVEL))

    def _y_to_value(self, y):
        f = _clamp((y - SLIDER_TOP) / SLIDER_TRAVEL, 0.0, 1.0)
        return DB_RANGE - f * (2 * DB_RANGE)

    def _slider_at(self, pos):
        for i in range(-1, BANDS):
            x = self._col_x(i)
            if QRect(x, SLIDER_TOP, THUMB_W, SLIDER_TRAVEL + THUMB_H).contains(pos):
                return i
        return None

    # -------------------------------------------------------------- audio
    def _apply(self):
        # The equalizer-10bands element has no preamp, so fold the preamp into
        # every band as a broadband gain (clamped to the element's range).
        for i in range(BANDS):
            val = _clamp(self._bands[i] + self._preamp, DB_MIN, DB_MAX) if self._on else 0.0
            self.eq.set_property('band%d' % i, val)

    # ------------------------------------------------------------ presets
    def _show_presets_menu(self, global_pos):
        menu = QMenu(self)
        for name, values in PRESETS:
            menu.addAction(name, lambda *a, v=values: self._apply_preset(v))
        menu.addSeparator()
        menu.addAction(_('Reset Preamp'), self._reset_preamp)
        menu.exec(global_pos)

    def _reset_preamp(self):
        self._preamp = 0.0
        if self._on:
            self._apply()
        self._save_station_eq()
        self.update()

    # ---------------------------------------------------- per-station EQ
    def _save_station_eq(self):
        sid = getattr(self.ctl, 'current_station_id', None)
        if sid is not None:
            self.ctl.set_station_eq(sid, self._bands, self._preamp)

    def _on_station_changed(self, station):
        sid = getattr(station, 'id', None)
        saved = self.ctl.get_station_eq(sid)
        if saved:
            bands = [_clamp(float(v), DB_MIN, DB_MAX) for v in saved.get('bands', [])]
            bands = (bands + [0.0] * BANDS)[:BANDS]
            self._bands = bands
            self._preamp = _clamp(float(saved.get('preamp', 0.0)), DB_MIN, DB_MAX)
            self._on = True
        else:
            # A station with no remembered EQ starts flat.
            self._bands = [0.0] * BANDS
            self._preamp = 0.0
        self._apply()
        self.update()

    def _apply_preset(self, values):
        self._bands = [_clamp(float(v), DB_MIN, DB_MAX) for v in values]
        self._preamp = 0.0
        if not self._on:                 # a preset implies the EQ is wanted
            self._on = True
        self._apply()
        self._save_station_eq()
        self.update()

    # -------------------------------------------------------------- paint
    def paintEvent(self, event):
        p = QPainter(self)
        s = self._scale()
        if s != 1:
            p.scale(s, s)
        p.drawImage(0, 0, self.skin.sprite('eqmain.bmp', 0, 0, W, H))
        active = self.isActiveWindow()
        p.drawImage(0, 0, self.skin.sprite('eqmain.bmp', 0, 134 if active else 149, W, TITLE_H))

        # Album art fills the area to the right of the (fixed-width) EQ face.
        if not self._collapsed and self._lw() > W:
            self._paint_album_art(p)

        if self._collapsed:
            p.end()
            return

        # ON button.
        sx, sy = (69, 119) if self._on else (10, 119)
        p.drawImage(ON_BTN.x(), ON_BTN.y(),
                    self.skin.sprite('eqmain.bmp', sx, sy, ON_BTN.width(), ON_BTN.height()))

        # Response-curve graph.
        self._paint_curve(p)

        # Sliders (preamp + 10 bands).
        thumb = self.skin.sprite('eqmain.bmp', 0, 176 if self._drag is not None else 164,
                                  THUMB_W, THUMB_H)
        p.drawImage(self._col_x(-1), self._value_to_y(self._preamp), thumb)
        for i in range(BANDS):
            p.drawImage(self._col_x(i), self._value_to_y(self._bands[i]), thumb)
        p.end()

    def _paint_album_art(self, p):
        gap = self._lw() - W
        side = min(gap, H)                 # square, bounded by the EQ height
        ax = W + (gap - side) // 2         # centered in the available gap
        ay = (H - side) // 2
        p.fillRect(W, 0, gap, H, Qt.black)
        song = getattr(self.ctl, 'current_song', None)
        art = getattr(song, 'art_pixbuf', None) if song is not None else None
        if art is not None and not art.isNull():
            scaled = art.scaled(side, side, Qt.KeepAspectRatioByExpanding,
                                Qt.SmoothTransformation)
            p.save()
            p.setClipRect(ax, ay, side, side)
            p.drawPixmap(ax - (scaled.width() - side) // 2,
                         ay - (scaled.height() - side) // 2, scaled)
            p.restore()

    def _paint_curve(self, p):
        p.save()
        p.setClipRect(GRAPH)
        pen = QPen(QColor(20, 200, 90))
        pen.setWidth(1)
        p.setPen(pen)
        pts = []
        for i in range(BANDS):
            x = GRAPH.x() + int(i * (GRAPH.width() - 1) / (BANDS - 1))
            db = self._bands[i] if self._on else 0.0
            f = _clamp((DB_RANGE - db) / (2 * DB_RANGE), 0.0, 1.0)
            y = GRAPH.y() + int(f * (GRAPH.height() - 1))
            pts.append((x, y))
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a[0], a[1], b[0], b[1])
        p.restore()

    # -------------------------------------------------------------- mouse
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = (event.position() / self._scale()).toPoint()
        if CLOSE_BTN.contains(pos):
            self._close_panel()
            return
        if MIN_BTN.contains(pos):
            self._toggle_collapse()
            return
        if ON_BTN.contains(pos):
            self._on = not self._on
            self._apply()
            self._save_station_eq()
            self.update()
            return
        if PRESETS_BTN.contains(pos):
            self._show_presets_menu(event.globalPosition().toPoint())
            return
        i = self._slider_at(pos)
        if i is not None:
            self._drag = i
            self._set_from_y(i, pos.y())
        elif pos.y() < TITLE_H:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            self._set_from_y(self._drag, (event.position() / self._scale()).y())

    def mouseReleaseEvent(self, event):
        if self._drag is not None:       # a band/preamp drag just finished
            self._drag = None
            self._save_station_eq()
        self.update()

    def _set_from_y(self, i, y):
        db = _clamp(self._y_to_value(y), DB_MIN, DB_MAX)
        if i == -1:
            self._preamp = db
        else:
            self._bands[i] = db
        if self._on:
            self._apply()         # re-push all bands (preamp is folded in)
        self.update()
