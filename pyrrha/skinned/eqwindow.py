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
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QMenu, QWidget

W, H = 275, 116
BANDS = 10

TITLE_H = 14
THUMB_W, THUMB_H = 11, 11
# Thumb-top range so the 11px thumb centers on the skin's +12/0/-12 dB track
# guides (base 2.91 has them at y=39/68/98).
SLIDER_TOP = 34
SLIDER_TRAVEL = 59          # vertical thumb travel (px)
PREAMP_X = 21
BAND_X0, BAND_DX = 78, 18   # band columns: 78, 96, ... 240 (spread out when wider)
GRAPH = QRect(86, 17, 113, 19)
ON_BTN = QRect(14, 18, 25, 12)
PRESETS_BTN = QRect(217, 18, 44, 12)   # opens the preset menu; sprite at (224,164)
MIN_BTN = QRect(254, 3, 9, 9)     # windowshade: collapse to the title bar
CLOSE_BTN = QRect(264, 3, 9, 9)   # close (hide) the panel

DB_RANGE = 12.0             # slider maps +/- this many dB (middle = 0)
DB_MIN, DB_MAX = -24.0, 12.0  # element's actual limits

# Slider well: the colored VU bar behind each thumb. 28 frames (2 rows of 14)
# in eqmain.bmp; magenta (255,0,255) is the transparency key. Skins without
# wells (e.g. Glare) leave this region magenta, so nothing is drawn.
WELL_W, WELL_H = 14, 63
WELL_TOP = 34
WELL_FRAMES = 28
MAGENTA = 0xFF00FF

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
        self._well_cache = {}       # frame index -> magenta-keyed QImage
        self._wells_present = None   # does this skin have slider wells?
        self._curve_colors_cache = None   # per-row EQ response-curve colors

        # Repaint the album art when the song or its artwork changes. The model's
        # dataChanged is the reliable trigger: art_callback always updates the row
        # (metadata_changed is skipped when the art cache write fails).
        controller.song_changed.connect(lambda *_: self.update())
        controller.metadata_changed.connect(lambda *_: self.update())
        model = getattr(controller, 'songs_model', None)
        if model is not None and hasattr(model, 'dataChanged'):
            model.dataChanged.connect(self._on_rows_changed)
        # Restore each station's remembered EQ when it becomes active.
        controller.station_changed_sig.connect(self._on_station_changed)

    def set_skin(self, skin):
        self.skin = skin
        self._well_cache = {}
        self._wells_present = None
        self._curve_colors_cache = None
        self.update()

    # ----------------------------------------------------------- slider wells
    def _has_wells(self):
        if self._wells_present is None:
            img = self.skin.image('eqmain.bmp')
            present = False
            if not img.isNull() and img.height() >= WELL_TOP + WELL_H:
                for fx in (17, 152, 212):     # a few well centers
                    c = img.pixelColor(fx, 190)
                    if max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue()) > 50:
                        present = True
                        break
            self._wells_present = present
        return self._wells_present

    def _well_sprite(self, frame):
        img = self._well_cache.get(frame)
        if img is None:
            col, row = frame % 14, frame // 14
            img = self.skin.sprite('eqmain.bmp', 13 + col * 15, 164 + row * 65,
                                   WELL_W, WELL_H).convertToFormat(QImage.Format_ARGB32)
            for y in range(img.height()):        # key out magenta transparency
                for x in range(img.width()):
                    if (img.pixel(x, y) & 0xFFFFFF) == MAGENTA:
                        img.setPixelColor(x, y, QColor(0, 0, 0, 0))
            self._well_cache[frame] = img
        return img

    def _band_frame(self, db):
        f = int(round((db + DB_RANGE) / (2 * DB_RANGE) * (WELL_FRAMES - 1)))
        return max(0, min(WELL_FRAMES - 1, f))

    def _scale(self):
        return getattr(self.window(), 'scale', 1)

    def _lw(self):
        shell = self.window()
        if getattr(shell, 'mode', 'modern') == 'classic':
            return W                       # native in classic mode (no album art)
        return max(W, int(getattr(shell, 'content_w', W)))

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

    def _on_rows_changed(self, top_left, bottom_right, *roles):
        # Repaint if the current song's row changed (e.g. its art just arrived).
        cur = getattr(self.ctl, 'current_song_index', None)
        if cur is not None and top_left.row() <= cur <= bottom_right.row():
            self.update()

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

        # Presets button (a sprite in most skins; some also bake it into the bg).
        p.drawImage(PRESETS_BTN.x(), PRESETS_BTN.y(),
                    self.skin.sprite('eqmain.bmp', 224, 164, PRESETS_BTN.width(), PRESETS_BTN.height()))

        # Response-curve graph.
        self._paint_curve(p)

        # Slider wells (the colored VU bar behind each thumb), if the skin has them.
        if self._has_wells():
            p.drawImage(self._col_x(-1) - 2, WELL_TOP, self._well_sprite(self._band_frame(self._preamp)))
            for i in range(BANDS):
                p.drawImage(self._col_x(i) - 2, WELL_TOP,
                            self._well_sprite(self._band_frame(self._bands[i])))

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

    def _skin_accent(self):
        """The skin's analyzer base color (VISCOLOR entry 2) — the same color the
        main window uses for the analyzer/scope/position bar. Used to theme the EQ
        curve when the skin defines no graph line colors of its own."""
        pal = []
        for line in self.skin.text('viscolor.txt').splitlines():
            parts = [x.strip() for x in line.split('//')[0].split(',')]
            if len(parts) >= 3 and parts[0]:
                try:
                    pal.append(QColor(int(parts[0]), int(parts[1]), int(parts[2])))
                except ValueError:
                    pass
        return pal[2] if len(pal) >= 3 else QColor(20, 200, 90)

    def _curve_colors(self):
        """19 per-row colors for the EQ response curve. Winamp skins bake a
        1px-wide, 19px-tall line-color strip into eqmain.bmp at (115, 294); use it
        when it's a real gradient. Skins that leave it flat/near-background (e.g.
        Glare) get the skin's theme accent instead of a hardcoded green."""
        if self._curve_colors_cache is not None:
            return self._curve_colors_cache
        img = self.skin.image('eqmain.bmp')
        strip = []
        if not img.isNull() and img.width() > 115 and img.height() >= 294 + GRAPH.height():
            strip = [img.pixelColor(115, 294 + row) for row in range(GRAPH.height())]
        distinct = {c.getRgb()[:3] for c in strip}
        if len(distinct) > 1:
            colors = strip                          # skin's own line gradient
        else:
            u = strip[0] if strip else None
            spread = max(u.red(), u.green(), u.blue()) - min(u.red(), u.green(), u.blue()) if u else 0
            vivid = u is not None and (spread > 30 or min(u.red(), u.green(), u.blue()) > 80)
            base = u if vivid else self._skin_accent()
            colors = [base] * GRAPH.height()
        self._curve_colors_cache = colors
        return colors

    def _paint_curve(self, p):
        colors = self._curve_colors()
        last = len(colors) - 1
        h, w = GRAPH.height(), GRAPH.width()
        ys = []
        for i in range(BANDS):
            db = self._bands[i] if self._on else 0.0
            f = _clamp((DB_RANGE - db) / (2 * DB_RANGE), 0.0, 1.0)
            ys.append(f * (h - 1))
        p.save()
        p.setClipRect(GRAPH)
        prev = None
        for x in range(w):
            t = x * (BANDS - 1) / max(1, w - 1)     # interpolate between band anchors
            i0 = int(t)
            i1 = min(BANDS - 1, i0 + 1)
            frac = t - i0
            row = max(0, min(h - 1, int(round(ys[i0] * (1 - frac) + ys[i1] * frac))))
            if prev is None:
                p.fillRect(GRAPH.x() + x, GRAPH.y() + row, 1, 1, colors[min(last, row)])
            else:                                    # fill the vertical span for a solid line
                lo, hi = (prev, row) if prev <= row else (row, prev)
                for r in range(lo, hi + 1):
                    p.fillRect(GRAPH.x() + x, GRAPH.y() + r, 1, 1, colors[min(last, r)])
            prev = row
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

    def contextMenuEvent(self, event):
        self._show_presets_menu(event.globalPos())   # right-click -> presets

    def wheelEvent(self, event):
        self.window().wheelEvent(event)               # scroll -> volume

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
