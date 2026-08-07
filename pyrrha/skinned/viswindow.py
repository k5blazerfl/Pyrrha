# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""A large, resizable visualizer window — the analyzer/oscilloscope the main
window shows in miniature, blown up to a full canvas.

It reads the controller's ``spectrum_bands`` (fed by the GStreamer ``spectrum``
element) and, by default, colors itself from the loaded skin's ``VISCOLOR.TXT``.
Modes: Bars, Dots, Lines, Oscilloscope, Spectrogram (a scrolling waterfall) and
Starfield (an audio-driven particle field). A peak-hold toggle freezes the
analyzer caps at their maxima; color presets (Skin/Heat/Mono/Ice) recolor
everything; sensitivity and falloff are tunable. Double-click or F toggles
fullscreen; right-click switches everything.
"""

import math
import random

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPolygon
from PySide6.QtWidgets import QMenu, QWidget

VIS_BARS, VIS_DOTS, VIS_LINES, VIS_SCOPE, VIS_WATERFALL, VIS_STARFIELD = range(6)
_MODE_NAMES = {VIS_BARS: 'Bars', VIS_DOTS: 'Dots', VIS_LINES: 'Lines',
               VIS_SCOPE: 'Oscilloscope', VIS_WATERFALL: 'Spectrogram',
               VIS_STARFIELD: 'Starfield'}
_MODE_KEYS = {Qt.Key_1: VIS_BARS, Qt.Key_2: VIS_DOTS, Qt.Key_3: VIS_LINES,
              Qt.Key_4: VIS_SCOPE, Qt.Key_5: VIS_WATERFALL, Qt.Key_6: VIS_STARFIELD}

PRESET_SKIN, PRESET_HEAT, PRESET_MONO, PRESET_ICE = range(4)
_PRESET_NAMES = {PRESET_SKIN: 'Skin', PRESET_HEAT: 'Heat',
                 PRESET_MONO: 'Mono', PRESET_ICE: 'Ice'}

PEAK_GRAVITY = 0.004     # peak-cap fall acceleration (per frame^2)
WAVE_HARMONICS = 16      # low spectrum bins summed into the scope wave
FRAME_MS = 33            # ~30 fps render tick
STAR_COUNT = 240

_SENSITIVITY = [('Low', 0.6), ('Normal', 1.0), ('High', 1.8)]
_FALLOFF = [('Slow', 0.025), ('Normal', 0.05), ('Fast', 0.11)]

_HEAT_STOPS = [(0, 0, 0), (8, 8, 40), (40, 0, 110), (110, 0, 150), (190, 30, 110),
               (235, 90, 45), (255, 165, 25), (255, 235, 120), (255, 255, 255)]
_ICE_STOPS = [(4, 10, 40), (0, 70, 150), (30, 170, 220), (150, 235, 245), (255, 255, 255)]


def _ramp_from_stops(stops, n):
    out, segs = [], len(stops) - 1
    for k in range(n):
        f = k / (n - 1) * segs
        i = min(segs - 1, int(f))
        t = f - i
        a, b = stops[i], stops[i + 1]
        out.append(QColor(int(a[0] + (b[0] - a[0]) * t),
                          int(a[1] + (b[1] - a[1]) * t),
                          int(a[2] + (b[2] - a[2]) * t)))
    return out


def _mono(n):
    return [QColor(v, v, v) for v in (24 + int(231 * i / (n - 1)) for i in range(n))]


def _resample(ramp, n):
    last = len(ramp) - 1
    return [ramp[min(last, round(i * last / (n - 1)))] for i in range(n)]


_HEAT = _ramp_from_stops(_HEAT_STOPS, 64)
_ICE = _ramp_from_stops(_ICE_STOPS, 64)
_ICE16 = _resample(_ICE, 16)


def parse_viscolors(skin):
    """(background, gradient[16], osc[5], peak) QColors from the skin's
    VISCOLOR.TXT, with classic-Winamp fallbacks."""
    pal = []
    for line in skin.text('viscolor.txt').splitlines():
        parts = [x.strip() for x in line.split('//')[0].split(',')]
        if len(parts) >= 3 and parts[0]:
            try:
                pal.append(QColor(int(parts[0]), int(parts[1]), int(parts[2])))
            except ValueError:
                pass
    if len(pal) >= 24:
        return (pal[0], pal[2:18], pal[18:23], pal[23])
    bg = QColor(0, 0, 0)
    grad = [QColor(int(255 * r / 15), int(255 * (1 - r / 15)), 40) for r in range(16)]
    osc = [QColor(180, 220, 130)] * 5
    return (bg, grad, osc, QColor(255, 255, 255))


class VisWindow(QWidget):
    """Resizable full-canvas visualizer sharing the controller + skin palette."""

    def __init__(self, controller, skin, shell):
        super().__init__(shell, Qt.Window)
        self.ctl = controller
        self.shell = shell
        self.setWindowTitle(_('Pyrrha Visualizer'))
        self.setMinimumSize(160, 90)
        self.resize(480, 240)
        self._mode = VIS_BARS
        self._preset = PRESET_SKIN
        self._peak_hold = False
        self._gain = 1.0
        self._falloff = _FALLOFF[1][1]

        self._bars = []          # current bar heights (0..1), sized to width
        self._peaks = []
        self._peak_vel = []
        self._edges = None       # (band_count, groups) -> log-spaced group edges
        self._wave = []          # oscilloscope samples (-1..1), one per px width
        self._wave_ph = [i * 0.7 for i in range(WAVE_HARMONICS)]
        self._wf = None          # spectrogram QImage (scrolls left each frame)
        self._stars = [[random.uniform(-1, 1), random.uniform(-1, 1),
                        random.uniform(0.05, 1.0)] for _ in range(STAR_COUNT)]

        self._skin_pal = parse_viscolors(skin)
        self.skin = skin
        self._recompute_palette()
        self._resize_state()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(FRAME_MS)

    # ------------------------------------------------------------ palette
    def set_skin(self, skin):
        self.skin = skin
        self._skin_pal = parse_viscolors(skin)
        self._recompute_palette()

    def _recompute_palette(self):
        bg, sk_grad, sk_osc, sk_peak = self._skin_pal
        p = self._preset
        if p == PRESET_SKIN:
            self._bg = bg
            self._grad = sk_grad
            self._osc_color = sk_osc[2] if len(sk_osc) > 2 else QColor(180, 220, 130)
            self._peak_color = sk_peak
            self._wf_ramp = _HEAT            # skin analyzer palettes read flat as a waterfall
        elif p == PRESET_HEAT:
            self._bg = QColor(0, 0, 0)
            self._grad = _resample(_HEAT, 16)
            self._osc_color = QColor(255, 170, 40)
            self._peak_color = QColor(255, 255, 255)
            self._wf_ramp = _HEAT
        elif p == PRESET_MONO:
            self._bg = QColor(0, 0, 0)
            self._grad = _mono(16)
            self._osc_color = QColor(210, 210, 210)
            self._peak_color = QColor(255, 255, 255)
            self._wf_ramp = _mono(64)
        else:  # PRESET_ICE
            self._bg = QColor(2, 6, 20)
            self._grad = _ICE16
            self._osc_color = QColor(120, 230, 245)
            self._peak_color = QColor(255, 255, 255)
            self._wf_ramp = _ICE
        if self._wf is not None:
            self._wf.fill(self._bg)
        self.update()

    # ------------------------------------------------------------ sizing
    def _resize_state(self):
        w, h = max(1, self.width()), max(1, self.height())
        nbars = max(8, min(72, w // 10))
        if len(self._bars) != nbars:
            self._bars = [0.0] * nbars
            self._peaks = [0.0] * nbars
            self._peak_vel = [0.0] * nbars
            self._edges = None
        if len(self._wave) != w:
            self._wave = [0.0] * w
        if self._wf is None or self._wf.width() != w or self._wf.height() != h:
            self._wf = QImage(w, h, QImage.Format_RGB32)
            self._wf.fill(self._bg)

    def resizeEvent(self, event):
        self._resize_state()
        super().resizeEvent(event)

    def _group_edges(self, count, groups):
        """Log-spaced FFT-bin edges grouping ``count`` bands into ``groups``."""
        if self._edges and self._edges[0] == (count, groups):
            return self._edges[1]
        edges = [min(count, max(1, int(round(count ** (i / groups)))))
                 for i in range(groups + 1)]
        for i in range(1, len(edges)):
            if edges[i] <= edges[i - 1]:
                edges[i] = min(count, edges[i - 1] + 1)
        self._edges = ((count, groups), edges)
        return edges

    def _grouped(self, raw, groups):
        edges = self._group_edges(len(raw), groups)
        return [max(raw[edges[i]:edges[i + 1]] or raw[edges[i]:edges[i] + 1])
                for i in range(groups)]

    # ------------------------------------------------------------ animation
    def _advance_bars(self, raw):
        n = len(self._bars)
        targets = self._grouped(raw, n) if raw else [0.0] * n
        for i in range(n):
            t = targets[i]
            self._bars[i] = t if t >= self._bars[i] else max(t, self._bars[i] - self._falloff)
            if self._bars[i] >= self._peaks[i]:
                self._peaks[i] = self._bars[i]
                self._peak_vel[i] = 0.0
            elif not self._peak_hold:
                self._peak_vel[i] += PEAK_GRAVITY
                self._peaks[i] = max(0.0, self._peaks[i] - self._peak_vel[i])

    def _advance_wave(self, raw):
        n = len(self._wave)
        if raw:
            amps = raw[:WAVE_HARMONICS]
            two_pi = 2.0 * math.pi
            for i in range(len(amps)):
                self._wave_ph[i] = (self._wave_ph[i] + 0.20 + 0.10 * i) % two_pi
            for x in range(n):
                t = x / n
                s = sum(a * math.sin(two_pi * (i + 1) * t + self._wave_ph[i])
                        for i, a in enumerate(amps))
                self._wave[x] = math.tanh(s * 0.8)
        else:
            for x in range(n):
                self._wave[x] *= 0.82

    def _advance_waterfall(self, raw):
        w, h = self._wf.width(), self._wf.height()
        self._wf = self._wf.copy(1, 0, w, h)     # drop the leftmost column
        col = self._grouped(raw, h) if raw else [0.0] * h
        ramp = self._wf_ramp
        last = len(ramp) - 1
        for row in range(h):
            self._wf.setPixelColor(w - 1, h - 1 - row,
                                   ramp[min(last, int(col[row] * (last + 1)))])

    def _advance_starfield(self, loudness):
        speed = 0.008 + loudness * 0.06
        for s in self._stars:
            s[2] -= speed
            if s[2] <= 0.03:
                s[0] = random.uniform(-1, 1)
                s[1] = random.uniform(-1, 1)
                s[2] = 1.0

    def _tick(self):
        playing = self.ctl.playing
        raw = getattr(self.ctl, 'spectrum_bands', None) if playing else None
        if raw and self._gain != 1.0:
            raw = [min(1.0, v * self._gain) for v in raw]
        m = self._mode
        if m == VIS_SCOPE:
            self._advance_wave(raw)
        elif m == VIS_WATERFALL:
            self._advance_waterfall(raw)
        elif m == VIS_STARFIELD:
            self._advance_bars(raw)
            loud = sum(self._bars) / len(self._bars) if self._bars else 0.0
            self._advance_starfield(loud)
        else:
            self._advance_bars(raw)
        self.update()

    # ------------------------------------------------------------ paint
    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        if self._mode == VIS_WATERFALL:
            p.drawImage(0, 0, self._wf)
            return
        p.fillRect(0, 0, w, h, self._bg)
        if self._mode == VIS_SCOPE:
            self._paint_scope(p, w, h)
        elif self._mode == VIS_STARFIELD:
            self._paint_starfield(p, w, h)
        else:
            self._paint_bars(p, w, h)   # bars / dots / lines

    def _bar_gradient(self, h):
        grad = QLinearGradient(0, h, 0, 0)
        stops = len(self._grad)
        for i, c in enumerate(self._grad):
            grad.setColorAt(i / (stops - 1), c)
        return QBrush(grad)

    def _paint_bars(self, p, w, h):
        n = len(self._bars)
        pitch = w / n
        bar_w = max(1, int(pitch) - 1)
        last = len(self._grad) - 1
        brush = self._bar_gradient(h) if self._mode == VIS_BARS else None
        pts = []
        for i in range(n):
            x = int(i * pitch)
            bh = int(self._bars[i] * h)
            if self._mode == VIS_BARS:
                if bh > 0:
                    p.fillRect(x, h - bh, bar_w, bh, brush)
                pr = int(self._peaks[i] * (h - 1))
                if pr > 0:
                    p.fillRect(x, h - pr - 1, bar_w, 2, self._peak_color)
            elif self._mode == VIS_DOTS:
                color = self._grad[min(last, int(self._bars[i] * (last + 1)))]
                p.fillRect(x, h - max(2, bh) - 1, bar_w, 3, color)
            else:  # VIS_LINES — silhouette across the bar tops
                pts.append(QPoint(x + bar_w // 2, h - bh))
        if self._mode == VIS_LINES and len(pts) > 1:
            p.setPen(self._grad[min(last, last)])
            p.drawPolyline(QPolygon(pts))

    def _paint_scope(self, p, w, h):
        mid = h // 2
        amp = (h - 1) / 2.0
        pts = [QPoint(x, max(0, min(h - 1, mid - int(self._wave[x] * amp))))
               for x in range(min(w, len(self._wave)))]
        if len(pts) > 1:
            p.setPen(self._osc_color)
            p.drawPolyline(QPolygon(pts))

    def _paint_starfield(self, p, w, h):
        cx, cy = w / 2, h / 2
        scale = min(w, h) * 0.5
        last = len(self._grad) - 1
        for x0, y0, z in self._stars:
            sx = cx + (x0 / z) * scale
            sy = cy + (y0 / z) * scale
            if 0 <= sx < w and 0 <= sy < h:
                size = max(1, int((1 - z) * 4) + 1)
                p.fillRect(int(sx), int(sy), size, size,
                           self._grad[min(last, int((1 - z) * (last + 1)))])

    # ------------------------------------------------------------ interaction
    def set_mode(self, mode):
        self._mode = mode
        self.update()

    def set_preset(self, preset):
        self._preset = preset
        self._recompute_palette()

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def adjust_gain(self, delta):
        self._gain = max(0.4, min(3.0, round(self._gain + delta, 2)))

    def mouseDoubleClickEvent(self, event):
        self.toggle_fullscreen()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        for mode in range(6):
            a = menu.addAction(_(_MODE_NAMES[mode]), lambda *_a, m=mode: self.set_mode(m))
            a.setCheckable(True)
            a.setChecked(self._mode == mode)
        menu.addSeparator()
        ph = menu.addAction(_('Peak Hold') + '\tP', lambda: self._toggle_peak_hold())
        ph.setCheckable(True)
        ph.setChecked(self._peak_hold)
        color = menu.addMenu(_('Color'))
        for preset in range(4):
            a = color.addAction(_(_PRESET_NAMES[preset]),
                                lambda *_a, pr=preset: self.set_preset(pr))
            a.setCheckable(True)
            a.setChecked(self._preset == preset)
        sens = menu.addMenu(_('Sensitivity'))
        for label, g in _SENSITIVITY:
            a = sens.addAction(_(label), lambda *_a, gg=g: setattr(self, '_gain', gg))
            a.setCheckable(True)
            a.setChecked(abs(self._gain - g) < 0.01)
        fall = menu.addMenu(_('Falloff'))
        for label, f in _FALLOFF:
            a = fall.addAction(_(label), lambda *_a, ff=f: setattr(self, '_falloff', ff))
            a.setCheckable(True)
            a.setChecked(abs(self._falloff - f) < 0.001)
        menu.addSeparator()
        fs = menu.addAction(_('Fullscreen') + '\tF', self.toggle_fullscreen)
        fs.setCheckable(True)
        fs.setChecked(self.isFullScreen())
        menu.addAction(_('Close'), self.close)
        menu.exec(event.globalPos())

    def _toggle_peak_hold(self):
        self._peak_hold = not self._peak_hold

    # ------------------------------------------------------------ lifecycle
    def showEvent(self, event):
        if not self._timer.isActive():
            self._timer.start(FRAME_MS)
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_F:
            self.toggle_fullscreen()
        elif key == Qt.Key_Escape:
            self.showNormal() if self.isFullScreen() else self.close()
        elif key == Qt.Key_Space:
            self.ctl.user_playpause()
        elif key == Qt.Key_P:
            self._toggle_peak_hold()
        elif key == Qt.Key_Up:
            self.adjust_gain(0.1)
        elif key == Qt.Key_Down:
            self.adjust_gain(-0.1)
        elif key in _MODE_KEYS:
            self.set_mode(_MODE_KEYS[key])
        else:
            super().keyPressEvent(event)
