# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""A large, resizable visualizer window — the analyzer/oscilloscope the main
window shows in miniature, blown up to a full canvas with a spectrogram mode.

It reads the controller's ``spectrum_bands`` (fed by the GStreamer ``spectrum``
element) and colors itself from the loaded skin's ``VISCOLOR.TXT``, so it stays
of a piece with the classic view. Modes: Bars (with falling peak caps),
Oscilloscope, and Spectrogram (a scrolling waterfall). Double-click or F toggles
fullscreen; right-click switches modes.
"""

import math

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPolygon
from PySide6.QtWidgets import QMenu, QWidget

VIS_BARS, VIS_SCOPE, VIS_WATERFALL = range(3)
_MODE_NAMES = {VIS_BARS: 'Bars', VIS_SCOPE: 'Oscilloscope', VIS_WATERFALL: 'Spectrogram'}

BAR_FALL = 0.05          # per-frame bar falloff (rise is instant)
PEAK_GRAVITY = 0.004     # peak-cap fall acceleration (per frame^2)
WAVE_HARMONICS = 16      # low spectrum bins summed into the scope wave
FRAME_MS = 33            # ~30 fps render tick


_HEAT_STOPS = [(0, 0, 0), (8, 8, 40), (40, 0, 110), (110, 0, 150), (190, 30, 110),
               (235, 90, 45), (255, 165, 25), (255, 235, 120), (255, 255, 255)]


def _build_heat(n=64):
    """A black→blue→magenta→orange→white heat ramp for the spectrogram (skin
    analyzer palettes are often monochrome, which reads flat as a waterfall)."""
    out, segs = [], len(_HEAT_STOPS) - 1
    for k in range(n):
        f = k / (n - 1) * segs
        i = min(segs - 1, int(f))
        t = f - i
        a, b = _HEAT_STOPS[i], _HEAT_STOPS[i + 1]
        out.append(QColor(int(a[0] + (b[0] - a[0]) * t),
                          int(a[1] + (b[1] - a[1]) * t),
                          int(a[2] + (b[2] - a[2]) * t)))
    return out


_HEAT = _build_heat()


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

        self._bars = []          # current bar heights (0..1), sized to width
        self._peaks = []
        self._peak_vel = []
        self._edges = None       # (band_count, nbars) -> log-spaced group edges
        self._wave = []          # oscilloscope samples (-1..1), one per px width
        self._wave_ph = [i * 0.7 for i in range(WAVE_HARMONICS)]
        self._wf = None          # spectrogram QImage (scrolls left each frame)
        self.set_skin(skin)
        self._resize_state()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(FRAME_MS)

    # ------------------------------------------------------------ palette
    def set_skin(self, skin):
        self.skin = skin
        self._bg, self._grad, self._osc, self._peak_color = parse_viscolors(skin)
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

    # ------------------------------------------------------------ animation
    def _grouped(self, raw, groups):
        """Peak magnitude of each of ``groups`` log-spaced band groups."""
        edges = self._group_edges(len(raw), groups)
        return [max(raw[edges[i]:edges[i + 1]] or raw[edges[i]:edges[i] + 1])
                for i in range(groups)]

    def _advance_bars(self, raw):
        n = len(self._bars)
        targets = self._grouped(raw, n) if raw else [0.0] * n
        moving = False
        for i in range(n):
            t = targets[i]
            self._bars[i] = t if t >= self._bars[i] else max(t, self._bars[i] - BAR_FALL)
            if self._bars[i] >= self._peaks[i]:
                self._peaks[i] = self._bars[i]
                self._peak_vel[i] = 0.0
            else:
                self._peak_vel[i] += PEAK_GRAVITY
                self._peaks[i] = max(0.0, self._peaks[i] - self._peak_vel[i])
            if self._bars[i] > 0.001 or self._peaks[i] > 0.001:
                moving = True
        return moving

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
            return True
        moving = False
        for x in range(n):
            self._wave[x] *= 0.82
            if abs(self._wave[x]) > 0.002:
                moving = True
        return moving

    def _advance_waterfall(self, raw):
        """Scroll the spectrogram left one column and draw a new column at the
        right edge (bottom = low freq, top = high)."""
        w, h = self._wf.width(), self._wf.height()
        self._wf = self._wf.copy(1, 0, w, h)     # drop the leftmost column
        col = self._grouped(raw, h) if raw else [0.0] * h
        last = len(_HEAT) - 1
        for row in range(h):
            self._wf.setPixelColor(w - 1, h - 1 - row,
                                   _HEAT[min(last, int(col[row] * (last + 1)))])
        return bool(raw)

    def _tick(self):
        playing = self.ctl.playing
        raw = getattr(self.ctl, 'spectrum_bands', None) if playing else None
        if self._mode == VIS_SCOPE:
            self._advance_wave(raw)
        elif self._mode == VIS_WATERFALL:
            self._advance_waterfall(raw)
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
        else:
            self._paint_bars(p, w, h)

    def _paint_bars(self, p, w, h):
        n = len(self._bars)
        pitch = w / n
        bar_w = max(1, int(pitch) - 1)
        grad = QLinearGradient(0, h, 0, 0)
        stops = len(self._grad)
        for i, c in enumerate(self._grad):
            grad.setColorAt(i / (stops - 1), c)
        brush = QBrush(grad)
        for i in range(n):
            x = int(i * pitch)
            bh = int(self._bars[i] * h)
            if bh > 0:
                p.fillRect(x, h - bh, bar_w, bh, brush)
            pr = int(self._peaks[i] * (h - 1))
            if pr > 0:
                p.fillRect(x, h - pr - 1, bar_w, 2, self._peak_color)

    def _paint_scope(self, p, w, h):
        mid = h // 2
        amp = (h - 1) / 2.0
        pen = self._osc[2] if len(self._osc) > 2 else QColor(180, 220, 130)
        pts = [QPoint(x, max(0, min(h - 1, mid - int(self._wave[x] * amp))))
               for x in range(min(w, len(self._wave)))]
        if len(pts) > 1:
            p.setPen(pen)
            p.drawPolyline(QPolygon(pts))

    # ------------------------------------------------------------ interaction
    def set_mode(self, mode):
        self._mode = mode
        self.update()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def mouseDoubleClickEvent(self, event):
        self.toggle_fullscreen()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        for mode in (VIS_BARS, VIS_SCOPE, VIS_WATERFALL):
            a = menu.addAction(_(_MODE_NAMES[mode]), lambda *_a, m=mode: self.set_mode(m))
            a.setCheckable(True)
            a.setChecked(self._mode == mode)
        menu.addSeparator()
        fs = menu.addAction(_('Fullscreen') + '\tF', self.toggle_fullscreen)
        fs.setCheckable(True)
        fs.setChecked(self.isFullScreen())
        menu.addAction(_('Close'), self.close)
        menu.exec(event.globalPos())

    def showEvent(self, event):
        if not self._timer.isActive():        # resume animation when shown
            self._timer.start(FRAME_MS)
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()                    # don't animate a hidden/closed window
        super().hideEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_F:
            self.toggle_fullscreen()
        elif key == Qt.Key_Escape:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.close()
        elif key == Qt.Key_Space:
            self.ctl.user_playpause()
        elif key in (Qt.Key_1, Qt.Key_2, Qt.Key_3):
            self.set_mode({Qt.Key_1: VIS_BARS, Qt.Key_2: VIS_SCOPE,
                           Qt.Key_3: VIS_WATERFALL}[key])
        else:
            super().keyPressEvent(event)
