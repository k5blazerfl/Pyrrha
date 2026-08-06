# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""The classic Winamp skinned main window (prototype).

Renders a fixed 275x116 frameless window entirely from a :class:`Skin`'s
sprites and drives a controller (a ``PyrrhaWindow``). Coordinates follow the
classic Winamp 2 skin spec; a few (title/time placement) are easy to tune
against a real skin.
"""

import logging
import math
import os
import time

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFileDialog, QMenu, QWidget

from .eqwindow import SkinnedEqWindow
from .font import CHAR_H, CHAR_W, NUM_H, NUM_W, NumberFont, TextFont
from .playlistwindow import SkinnedPlaylistWindow

W, H = 275, 116  # classic main-window native size
WMAX = 1600      # max logical content width the shell can grow to

# The main window stretches by keeping a fixed left slice and a fixed
# right-anchored slice, filling the inserted gap with the skin's own pixels.
SPLIT = 219      # width of the left slice kept as-is (right slice = W-SPLIT)
TB_CORNER = 25   # title-bar end-cap width (carries the menu/close/min glyphs)
TB_TITLE = 100   # centered title graphic width, re-centered as the bar widens

# name, dest x/y/w/h, source x, source y (normal), source y (pressed)
BUTTONS = [
    ('prev', 16, 88, 23, 18, 0, 0, 18),
    ('play', 39, 88, 23, 18, 23, 0, 18),
    ('pause', 62, 88, 23, 18, 46, 0, 18),
    ('stop', 85, 88, 23, 18, 69, 0, 18),
    ('next', 108, 88, 22, 18, 92, 0, 18),
    ('eject', 136, 89, 22, 16, 114, 0, 16),
]

TITLEBAR = (0, 0, 275, 14)          # dest; src active (27,0), inactive (27,15)
MENU = QRect(6, 3, 9, 9)            # top-left main-menu (options) button
CLOSE = QRect(264, 3, 9, 9)
# Main title bar buttons: minimize (to taskbar) and windowshade (collapse).
MINIMIZE = QRect(244, 3, 9, 9)
SHADE_BTN = QRect(254, 3, 9, 9)
# EQ / playlist toggle buttons (from shufrep.bmp): open or close those panels.
EQ_TOGGLE = QRect(219, 58, 23, 12)
PL_TOGGLE = QRect(242, 58, 23, 12)
# Shuffle/repeat toggles (shufrep.bmp): off row y=0, on row y=30. Affect local
# playback only. Shuffle 47x15 at (28,y); Repeat 28x15 at (0,y).
SHUFFLE = QRect(164, 89, 47, 15)
REPEAT = QRect(210, 89, 28, 15)
VOLUME = QRect(107, 57, 68, 13)     # slider background area
VOL_HANDLE_W = 14
BALANCE = QRect(177, 57, 38, 13)    # stereo balance slider (right of volume)
BAL_HANDLE_W = 14
BAL_SNAP = 0.08                     # dead-zone that snaps the handle to center
TITLE_AREA = QRect(111, 27, 154, CHAR_H)   # song-title marquee (centered in the display box)
TIME_POS = [(48, 26), (60, 26), (78, 26), (90, 26)]  # MM:SS digit slots
MINUS_POS = (36, 26)                # leading "-" shown in remaining-time mode
TIME_RECT = QRect(36, 24, 66, 16)   # click to toggle elapsed <-> remaining
STATUS_POS = (26, 28)               # play/pause/stop indicator
# Clutterbar: the classic O/A/I/D/V strip Winamp draws on the display's left
# edge (the skin doesn't supply it). Each letter is a tiny clickable button.
CLUTTER_X = 10
CLUTTER = [('O', 22), ('A', 30), ('I', 38), ('D', 46), ('V', 54)]
VIS = QRect(22, 45, 78, 16)         # spectrum-analyzer visualization area (x=22, baseline y=60)
POSBAR = QRect(16, 72, 248, 10)     # song-progress bar (non-interactive); stretches
POSBAR_RIGHT_MARGIN = W - (POSBAR.x() + POSBAR.width())   # native gap to the right edge (11)
POSBAR_THUMB_W = 29                 # posbar.bmp: bg (0,0,248,10), thumb (248,0,29,10)
KBPS_POS = (111, 43)                 # bitrate number (small font, before "kbps")
KHZ_POS = (156, 43)                  # sample-rate number (before "kHz")
STEREO_POS = (239, 41)              # from monoster.bmp: (0,0) lit / (0,12) dim
MONO_POS = (212, 41)               # from monoster.bmp: (29,0) lit / (29,12) dim
VIS_BARS = 19                       # analyzer bars (76px / 4px pitch)
BAR_FALL = 0.09                     # per-frame bar falloff (rise is instant)
PEAK_GRAVITY = 0.007                # peak-cap fall acceleration (per frame^2)
WAVE_HARMONICS = 24                 # low spectrum bins summed into the scope wave

# Visualizer modes cycled by clicking the display / clutterbar 'V'.
VIS_BARS_MODE, VIS_LINES, VIS_DOTS, VIS_SCOPE, VIS_OFF = range(5)
VIS_MODES = 5

# Classic Winamp "nullsoft" easter egg: type n, u, l, Esc, l, Esc, s, o, f, t
# (i.e. "nullsoft" with Escape pressed after each 'l') to flash the llama line.
EGG_SEQUENCE = ('n', 'u', 'l', 'esc', 'l', 'esc', 's', 'o', 'f', 't')
EGG_MESSAGE = "IT REALLY WHIPS THE LLAMA'S ASS!"


class SkinnedWindow(QWidget):
    def __init__(self, controller, skin, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint if parent is None else Qt.Widget)
        self.ctl = controller
        self.skin = skin
        self.text_font = TextFont(skin)
        self.num_font = NumberFont(skin)
        self.setFixedSize(W, H)
        self.setWindowTitle('Pyrrha')

        self._collapsed = False   # windowshade: collapsed to the title bar
        self._pressed = None      # currently-held transport button
        self._vol_dragging = False
        self._bal_dragging = False
        self._seek_dragging = False   # scrubbing the position bar (local files)
        self._seek_frac = 0.0         # preview fraction while scrubbing
        self._win_drag = None     # window-move offset
        self._scroll = 0          # marquee scroll offset
        self._time_remaining = False   # False = elapsed, True = remaining (-MM:SS)
        self._volume = float(controller.settings['volume'])
        self._balance = float(controller.settings['balance'])
        # Transient marquee readout (e.g. "Volume: 72%") shown while adjusting.
        self._readout = None
        self._readout_until = 0.0
        self._egg_progress = 0    # position in the "nullsoft" easter-egg sequence
        self._vis_colors = self._load_vis_colors()
        self._vis_active = False
        self._vis_mode = VIS_BARS_MODE      # click the display to cycle modes
        self._bar = [0.0] * VIS_BARS        # current bar heights (0..1)
        self._peak = [0.0] * VIS_BARS       # falling peak-cap positions
        self._peak_vel = [0.0] * VIS_BARS   # peak-cap velocities
        self._vis_edges_cache = None        # cached log-frequency bin edges
        self._wave = [0.0] * VIS.width()    # oscilloscope samples (-1..1)
        self._wave_ph = [i * 0.7 for i in range(WAVE_HARMONICS)]   # per-harmonic phase

        # Live updates from the controller.
        controller.song_changed.connect(lambda *_: self._reset_marquee())
        controller.play_state_changed.connect(lambda *_: self.update())
        controller.buffering_finished.connect(lambda *_: self.update())

        # Marquee scroll + time tick.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(220)

        # Faster tick for the spectrum-analyzer visualization.
        self._vis_timer = QTimer(self)
        self._vis_timer.timeout.connect(self._vis_tick)
        self._vis_timer.start(50)

    def _load_vis_colors(self):
        """Per-row analyzer colors (bottom → top) from the skin's VISCOLOR.TXT
        (entries 2..17), resampled to the visualization height; a green → red
        gradient is used when the skin has no palette. Also sets the peak-cap
        color (entry 23, the Winamp peak color)."""
        pal = []
        for line in self.skin.text('viscolor.txt').splitlines():
            parts = [x.strip() for x in line.split('//')[0].split(',')]
            if len(parts) >= 3 and parts[0]:
                try:
                    pal.append(QColor(int(parts[0]), int(parts[1]), int(parts[2])))
                except ValueError:
                    pass
        if len(pal) >= 18:
            grad = pal[2:18]
        else:
            grad = [QColor(int(255 * r / 15), int(255 * (1 - r / 15)), 40)
                    for r in range(16)]
        self._peak_color = pal[23] if len(pal) >= 24 else QColor(255, 255, 255)
        # Oscilloscope colors (VISCOLOR entries 18..22), indexed by displacement.
        self._osc_colors = pal[18:23] if len(pal) >= 23 else [QColor(0, 255, 0)]
        # Skin accent (analyzer base color) — used for the position-bar fill.
        self._accent = pal[2] if len(pal) >= 3 else QColor(31, 104, 236)
        h = VIS.height()
        return [grad[min(len(grad) - 1, r * len(grad) // h)] for r in range(h)]

    def _vis_edges(self, count):
        """Log-spaced FFT-bin edges grouping ``count`` spectrum bands into
        VIS_BARS display bars (cached per band count)."""
        if self._vis_edges_cache and self._vis_edges_cache[0] == count:
            return self._vis_edges_cache[1]
        edges = [min(count, max(1, int(round((count / 1.0) ** (i / VIS_BARS)))))
                 for i in range(VIS_BARS + 1)]
        for i in range(1, len(edges)):        # keep strictly increasing
            if edges[i] <= edges[i - 1]:
                edges[i] = min(count, edges[i - 1] + 1)
        self._vis_edges_cache = (count, edges)
        return edges

    def _advance_vis(self, raw):
        """Step the bar/peak animation one frame toward ``raw`` (the spectrum,
        or None to decay to silence). Returns True while anything is moving."""
        edges = self._vis_edges(len(raw)) if raw else None
        moving = False
        for i in range(VIS_BARS):
            if edges is not None:
                target = max(raw[edges[i]:edges[i + 1]] or raw[edges[i]:edges[i] + 1])
            else:
                target = 0.0
            # Bars rise instantly, fall gradually.
            if target >= self._bar[i]:
                self._bar[i] = target
            else:
                self._bar[i] = max(target, self._bar[i] - BAR_FALL)
            # Peak caps sit on new highs, then fall with gravity.
            if self._bar[i] >= self._peak[i]:
                self._peak[i] = self._bar[i]
                self._peak_vel[i] = 0.0
            else:
                self._peak_vel[i] += PEAK_GRAVITY
                self._peak[i] = max(0.0, self._peak[i] - self._peak_vel[i])
            if self._bar[i] > 0.001 or self._peak[i] > 0.001:
                moving = True
        return moving

    def _advance_wave(self, raw):
        """Step the oscilloscope one frame. Synthesizes a moving waveform from
        the low spectrum bands (magnitude-only data), scaled by overall loudness;
        decays to a flat line when silent. Returns True while anything moves."""
        n = len(self._wave)
        if raw:
            amps = raw[:WAVE_HARMONICS]
            energy = sum(amps)
            loud = min(1.0, energy / 6.0)             # overall level -> amplitude
            shape_norm = 1.0 / max(1.0, energy)       # keep the shape in ~[-1, 1]
            for i in range(len(amps)):
                self._wave_ph[i] += 0.15 + 0.05 * i   # higher bands scroll faster
            for x in range(n):
                t = x / n
                s = 0.0
                for i, a in enumerate(amps):
                    s += a * math.sin(2.0 * math.pi * (i + 1) * t + self._wave_ph[i])
                self._wave[x] = max(-1.0, min(1.0, s * shape_norm * loud * 1.3))
            return True
        moving = False
        for x in range(n):
            self._wave[x] *= 0.82
            if abs(self._wave[x]) > 0.002:
                moving = True
        return moving

    def _vis_tick(self):
        if self._vis_mode == VIS_OFF:      # visualizer off — no repaints needed
            return
        playing = self.ctl.playing
        raw = getattr(self.ctl, 'spectrum_bands', None) if playing else None
        if self._vis_mode == VIS_SCOPE:
            moving = self._advance_wave(raw)
        else:
            moving = self._advance_vis(raw)
        if playing or moving or self._vis_active:
            self.update()
        self._vis_active = playing or moving

    # ---------------------------------------------------------------- helpers
    def set_skin(self, skin):
        self.skin = skin
        self.text_font = TextFont(skin)
        self.num_font = NumberFont(skin)
        self._vis_colors = self._load_vis_colors()   # also refreshes accent/peak
        self.update()

    def _load_skin_file(self):
        path, _sel = QFileDialog.getOpenFileName(
            self, _('Load Winamp Skin'), self.ctl.skins_dir(),
            _('Winamp skins (*.wsz *.zip);;All files (*)'))
        if path:
            self.window().load_skin(path)

    def _load_skin_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, _('Load Skin Folder'), self.ctl.skins_dir())
        if path:
            self.window().load_skin(path)

    def _title_text(self):
        if self._readout and time.monotonic() < self._readout_until:
            return self._readout
        song = self.ctl.current_song
        if song is None:
            return 'PYRRHA'
        return '{} - {}'.format(song.artist, song.title)

    def _show_readout(self, text, secs=1.2):
        """Briefly replace the title marquee with a status line (volume/balance),
        the way Winamp flashes the level while you drag a slider."""
        self._readout = text
        self._readout_until = time.monotonic() + secs
        self._reset_marquee()   # show it from the start, un-scrolled

    def egg_key(self, event):
        """Feed a key press to the classic 'nullsoft' easter egg matcher. Returns
        True if the key was consumed by the sequence (matched or restarted it)."""
        if event.key() == Qt.Key_Escape:
            token = 'esc'
        else:
            text = event.text().lower()
            if len(text) != 1 or not text.isalpha():
                self._egg_progress = 0
                return False
            token = text
        if token == EGG_SEQUENCE[self._egg_progress]:
            self._egg_progress += 1
            if self._egg_progress == len(EGG_SEQUENCE):
                self._egg_progress = 0
                self._show_readout(EGG_MESSAGE, secs=3.0)
            return True
        # Mismatch: reset, but let this key start a fresh sequence.
        self._egg_progress = 1 if token == EGG_SEQUENCE[0] else 0
        return self._egg_progress == 1

    def _reset_marquee(self):
        self._scroll = 0
        self.update()

    def _tick(self):
        self._scroll += 1
        self.update()

    def _time_display(self):
        """(MMSS string, is_remaining). Remaining shows a leading '-'."""
        pos = self.ctl.query_position()
        if pos is None:
            return '    ', False
        secs = int(pos // 1_000_000_000)
        if self._time_remaining:
            dur = self.ctl.query_duration()
            if dur and dur > 0:
                secs = max(0, int(dur // 1_000_000_000) - secs)
                return '{:02d}{:02d}'.format((secs // 60) % 100, secs % 60), True
        return '{:02d}{:02d}'.format((secs // 60) % 100, secs % 60), False

    def _status_sprite_x(self):
        if not self.ctl.playing:
            return 9   # pause
        return 0       # play

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event):
        p = QPainter(self)
        s = self._scale()
        if s != 1:
            p.scale(s, s)   # everything below is drawn in logical coords

        lw = self._lw()
        if self._collapsed:   # windowshade: draw only the title bar
            self._paint_titlebar(p, lw)
            p.end()
            return
        gap = lw - W        # extra width to fill (0 at native size)
        dx = gap            # right-anchored controls shift by this much
        rkeep = W - SPLIT   # width of the right slice, anchored to the right edge

        # Background: fixed left slice, the skin's own pixels stretched across
        # the gap (features on the main window run horizontally, so a 1px column
        # tiles cleanly), then the fixed right slice anchored to the right.
        p.drawImage(0, 0, self.skin.sprite('main.bmp', 0, 0, SPLIT, H))
        if gap:
            p.drawImage(QRect(SPLIT, 0, gap, H),
                        self.skin.sprite('main.bmp', SPLIT - 1, 0, 1, H))
        p.drawImage(lw - rkeep, 0, self.skin.sprite('main.bmp', SPLIT, 0, rkeep, H))

        # Title bar: tile the fill across the full width, keep the end corners
        # (which carry the menu/close/minimize glyphs), and re-center the title
        # graphic so it stays centered as the window widens.
        self._paint_titlebar(p, lw)

        # Playback status indicator (left-anchored).
        p.drawImage(STATUS_POS[0], STATUS_POS[1],
                    self.skin.sprite('playpaus.bmp', self._status_sprite_x(), 0, 9, 9))

        # Clutterbar (classic Winamp O/A/I/D/V strip on the display's left edge).
        if getattr(self.window(), 'mode', 'modern') == 'classic':
            self._paint_clutterbar(p)

        # Time (MM SS) (left-anchored); a leading "-" marks remaining time.
        tstr, remaining = self._time_display()
        for (x, y), ch in zip(TIME_POS, tstr):
            p.drawImage(x, y, self.num_font.digit(ch))
        if remaining:
            p.drawImage(MINUS_POS[0], MINUS_POS[1], self.num_font.digit('-'))

        # Song-title marquee (clipped, scrolling) — widened to fill the gap.
        self._paint_marquee(p, gap)

        # Spectrum-analyzer visualization (left-anchored).
        self._paint_visualizer(p)

        # Bitrate / sample-rate / stereo indicators (left-anchored).
        self._paint_stream_info(p)

        # Song-progress bar. Draggable to seek for local files; Pandora streams
        # aren't seekable, so it's display-only there (see ctl.seekable()).
        self._paint_position(p)

        # Volume: filled background frame + handle (left-anchored).
        level = min(27, max(0, round(self._volume * 27)))
        p.drawImage(VOLUME.x(), VOLUME.y(),
                    self.skin.sprite('volume.bmp', 0, level * 15, 68, 13))
        hx = VOLUME.x() + round(self._volume * (VOLUME.width() - VOL_HANDLE_W))
        p.drawImage(hx, VOLUME.y() + 1,
                    self.skin.sprite('volume.bmp',
                                     0 if self._vol_dragging else 15, 422, VOL_HANDLE_W, 11))

        # Balance: background frame (row 0 = centered) + handle (left-anchored).
        if self.skin.has('balance.bmp'):
            blvl = min(27, round(abs(self._balance) * 27))
            p.drawImage(BALANCE.x(), BALANCE.y(),
                        self.skin.sprite('balance.bmp', 9, blvl * 15, 38, 13))
            bhx = BALANCE.x() + round((self._balance + 1) / 2 * (BALANCE.width() - BAL_HANDLE_W))
            p.drawImage(bhx, BALANCE.y() + 1,
                        self.skin.sprite('balance.bmp',
                                         0 if self._bal_dragging else 15, 422, BAL_HANDLE_W, 11))

        # Transport buttons (left-anchored).
        for name, bx, by, w, h, sx, sy_n, sy_p in BUTTONS:
            sy = sy_p if self._pressed == name else sy_n
            p.drawImage(bx, by, self.skin.sprite('cbuttons.bmp', sx, sy, w, h))

        # EQ / playlist toggle buttons (right-anchored, lit when the panel is open).
        shell = self.window()
        for panel, rect, sx in ((getattr(shell, 'eq', None), EQ_TOGGLE, 0),
                                (getattr(shell, 'pl', None), PL_TOGGLE, 23)):
            if panel is not None:
                sy = 73 if panel._closed else 61   # off / on
                p.drawImage(rect.x() + dx, rect.y(),
                            self.skin.sprite('shufrep.bmp', sx, sy, 23, 12))

        # Shuffle / repeat toggles (lit when on). Play order for local files.
        p.drawImage(SHUFFLE.x(), SHUFFLE.y(), self.skin.sprite(
            'shufrep.bmp', 28, 30 if getattr(self.ctl, 'shuffle', False) else 0, 47, 15))
        p.drawImage(REPEAT.x(), REPEAT.y(), self.skin.sprite(
            'shufrep.bmp', 0, 30 if getattr(self.ctl, 'repeat', False) else 0, 28, 15))
        p.end()

    def _paint_titlebar(self, p, lw):
        # Tile the fill across the full width, keep the end corners (menu/close/
        # minimize glyphs), and re-center the title graphic.
        ty = 0 if self.isActiveWindow() else 15
        p.drawImage(QRect(0, 0, lw, 14),
                    self.skin.sprite('titlebar.bmp', 27 + TB_CORNER + 1, ty, 1, 14))
        p.drawImage(0, 0, self.skin.sprite('titlebar.bmp', 27, ty, TB_CORNER, 14))
        p.drawImage(lw - TB_CORNER, 0,
                    self.skin.sprite('titlebar.bmp', 27 + W - TB_CORNER, ty, TB_CORNER, 14))
        p.drawImage((lw - TB_TITLE) // 2, 0,
                    self.skin.sprite('titlebar.bmp', 27 + (W - TB_TITLE) // 2, ty, TB_TITLE, 14))

    def _paint_marquee(self, p, gap):
        img = self.text_font.render(self._title_text() + '   ***   ')
        area = QRect(TITLE_AREA.x(), TITLE_AREA.y(),
                     TITLE_AREA.width() + gap, TITLE_AREA.height())
        p.save()
        p.setClipRect(area)
        span = max(img.width(), area.width())
        off = self._scroll % span if img.width() > area.width() else 0
        p.drawImage(area.x() - off, area.y(), img)
        if off:  # wrap-around copy
            p.drawImage(area.x() - off + span, area.y(), img)
        p.restore()

    def _posbar_geom(self):
        # Stretch the bar to the window width, keeping the native right margin.
        x, y, h = POSBAR.x(), POSBAR.y(), POSBAR.height()
        bar_w = max(1, self._lw() - x - POSBAR_RIGHT_MARGIN)
        return x, y, bar_w, h

    def _paint_position(self, p):
        x, y, bar_w, h = self._posbar_geom()
        p.drawImage(QRect(x, y, bar_w, h), self.skin.sprite('posbar.bmp', 0, 0, 248, 10))
        if self._seek_dragging:
            frac = self._seek_frac        # follow the cursor while scrubbing
        else:
            pos = self.ctl.query_position()
            dur = self.ctl.query_duration()
            if not (pos and dur and dur > 0):
                return
            frac = min(1.0, max(0.0, pos / dur))
        if getattr(self.window(), 'mode', 'modern') == 'classic':
            # Authentic Winamp slider knob from the skin.
            tx = x + int(frac * (bar_w - POSBAR_THUMB_W))
            p.drawImage(tx, y, self.skin.sprite('posbar.bmp', 248, 0, POSBAR_THUMB_W, h))
        else:
            # Modern: a blue (accent) progress fill with a bright leading cap.
            fill_w = int(frac * (bar_w - 2))
            if fill_w <= 0:
                return
            r = QRect(x + 1, y + 2, fill_w, h - 4)
            p.fillRect(r, self._accent)
            p.fillRect(QRect(r.right() - 1, r.y(), 2, r.height()), self._peak_color)

    def _paint_clutterbar(self, p):
        f = QFont()
        f.setPixelSize(6)
        f.setBold(True)
        p.setFont(f)
        shell = self.window()
        active = {'A': getattr(shell, 'keep_above', False),
                  'D': getattr(shell, 'scale', 1) > 1}
        for label, y in CLUTTER:
            p.setPen(QColor(210, 212, 220) if active.get(label) else QColor(96, 98, 108))
            p.drawText(QRect(CLUTTER_X, y, 7, 8), Qt.AlignCenter, label)

    def _clutter_action(self, label, gpos):
        c, shell = self.ctl, self.window()
        if label == 'O':                       # Options
            self._show_menu(gpos)
        elif label == 'A':                     # Always on top (KWin "keep above")
            shell.keep_above = not shell.keep_above
            if not self._kwin_keep_above(shell.keep_above):
                shell.setWindowFlag(Qt.WindowStaysOnTopHint, shell.keep_above)
                shell.show()                   # fallback: Qt hint + re-map
            self.update()
        elif label == 'I' and hasattr(c, 'info_song'):   # song Info
            c.info_song()
        elif label == 'D':                     # Size: cycle 1x -> 1.5x -> 2x
            cur = getattr(shell, 'scale', 1.0)
            shell.set_scale(1.5 if cur < 1.25 else 2.0 if cur < 1.75 else 1.0)
        elif label == 'V':                     # Visualization mode
            self._vis_mode = (self._vis_mode + 1) % VIS_MODES
            self.update()

    def _kwin_keep_above(self, above):
        """Set the window's keep-above state through KWin's D-Bus scripting
        interface (works on Wayland where the Qt hint is ignored). Returns True
        on success. Matches our window by app-id or caption."""
        import os
        import tempfile
        try:
            from gi.repository import Gio, GLib
        except Exception:
            return False
        js = ('(function(){\n'
              '  var l=(typeof workspace.windowList==="function")?workspace.windowList()\n'
              '        :(typeof workspace.clientList==="function")?workspace.clientList():[];\n'
              '  for(var i=0;i<l.length;i++){var c=l[i];\n'
              '    var rc=((c.resourceClass!=null)?c.resourceClass:"").toString().toLowerCase();\n'
              '    var cap=((c.caption!=null)?c.caption:"").toString();\n'
              '    if(rc.indexOf("pyrrha")!==-1||cap.indexOf("Pyrrha")!==-1){c.keepAbove=%s;}\n'
              '  }})();\n') % ('true' if above else 'false')
        fd, path = tempfile.mkstemp(suffix='.js', prefix='pyrrha-ka-')
        with os.fdopen(fd, 'w') as f:
            f.write(js)
        name = os.path.basename(path)
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            sid = None
            for sig, args in (('(ss)', (path, name)), ('(s)', (path,))):
                try:
                    r = bus.call_sync('org.kde.KWin', '/Scripting', 'org.kde.kwin.Scripting',
                                      'loadScript', GLib.Variant(sig, args),
                                      GLib.VariantType('(i)'), Gio.DBusCallFlags.NONE, 2000, None)
                    sid = r.unpack()[0]
                    break
                except GLib.Error:
                    continue
            if sid is None or sid < 0:
                return False
            bus.call_sync('org.kde.KWin', '/Scripting/Script%d' % sid, 'org.kde.kwin.Script',
                          'run', None, None, Gio.DBusCallFlags.NONE, 2000, None)
            try:
                bus.call_sync('org.kde.KWin', '/Scripting', 'org.kde.kwin.Scripting',
                              'unloadScript', GLib.Variant('(s)', (name,)),
                              None, Gio.DBusCallFlags.NONE, 2000, None)
            except GLib.Error:
                pass
            return True
        except GLib.Error as e:
            logging.debug('KWin keep-above via D-Bus failed: %s', e)
            return False
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _paint_stream_info(self, p):
        bitrate, rate, channels = self.ctl.audio_stream_info()
        if bitrate:
            p.drawImage(KBPS_POS[0], KBPS_POS[1], self.text_font.render('%3d' % bitrate))
        if rate:
            p.drawImage(KHZ_POS[0], KHZ_POS[1],
                        self.text_font.render('%2d' % round(rate / 1000)))
        stereo_y = 0 if channels == 2 else 12    # lit / dim
        mono_y = 0 if channels == 1 else 12
        p.drawImage(STEREO_POS[0], STEREO_POS[1],
                    self.skin.sprite('monoster.bmp', 0, stereo_y, 29, 12))
        p.drawImage(MONO_POS[0], MONO_POS[1],
                    self.skin.sprite('monoster.bmp', 29, mono_y, 27, 12))

    def _paint_scope(self, p):
        """Oscilloscope: a waveform line across the visualization area, colored
        by displacement from the center (VISCOLOR oscilloscope palette)."""
        osc = self._osc_colors
        last = len(osc) - 1
        mid = VIS.y() + VIS.height() // 2
        amp = (VIS.height() - 1) / 2.0
        prev_y = None
        for x in range(VIS.width()):
            v = self._wave[x]
            y = mid - int(round(v * amp))
            y = max(VIS.y(), min(VIS.bottom(), y))
            color = osc[min(last, int(abs(v) * (last + 1)))]
            px = VIS.x() + x
            if prev_y is None:
                p.fillRect(px, y, 1, 1, color)
            else:                      # join to the previous sample for a solid trace
                lo, hi = (prev_y, y) if prev_y <= y else (y, prev_y)
                p.fillRect(px, lo, 1, hi - lo + 1, color)
            prev_y = y

    def _paint_visualizer(self, p):
        if self._vis_mode == VIS_OFF:
            return
        if self._vis_mode == VIS_SCOPE:
            self._paint_scope(p)
            return
        colors = self._vis_colors
        top_row = len(colors) - 1
        bar_w = max(1, VIS.width() // VIS_BARS)
        w = max(1, bar_w - 1)          # 1px gap between bars
        bottom = VIS.bottom()
        height = VIS.height()
        for i in range(VIS_BARS):
            x = VIS.x() + i * bar_w
            h = int(round(self._bar[i] * height))
            if self._vis_mode == VIS_LINES:    # thin lines (1px wide)
                for row in range(h):
                    p.fillRect(x, bottom - row, 1, 1, colors[min(row, top_row)])
            elif self._vis_mode == VIS_DOTS:   # dots (top of each bar only)
                if h > 0:
                    p.fillRect(x, bottom - (h - 1), w, 1, colors[min(h - 1, top_row)])
            else:                      # bars (filled) with a falling peak cap
                for row in range(h):
                    p.fillRect(x, bottom - row, w, 1, colors[min(row, top_row)])
                pr = int(round(self._peak[i] * (height - 1)))
                if pr > 0:
                    p.fillRect(x, bottom - pr, w, 1, self._peak_color)

    # ------------------------------------------------------------------ mouse
    def _button_at(self, pos):
        for name, dx, dy, w, h, *_ in BUTTONS:
            if QRect(dx, dy, w, h).contains(pos):
                return name
        return None

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        # A click that activates an unfocused window only focuses it — don't
        # also fire a control (e.g. the clutterbar D would cycle the size).
        shell = self.window()
        if hasattr(shell, 'is_focus_click') and shell.is_focus_click():
            return
        pos = (event.position() / self._scale()).toPoint()   # logical coords
        dx = self._dx()
        if MENU.contains(pos):
            self._show_menu(event.globalPosition().toPoint())
            return
        if CLOSE.translated(dx, 0).contains(pos):
            self.ctl.quit()
            return
        if MINIMIZE.translated(dx, 0).contains(pos):
            self.window().showMinimized()
            return
        if SHADE_BTN.translated(dx, 0).contains(pos):
            self._toggle_shade()
            return
        if EQ_TOGGLE.translated(dx, 0).contains(pos):
            self.window().toggle_panel(getattr(self.window(), 'eq', None))
            return
        if PL_TOGGLE.translated(dx, 0).contains(pos):
            self.window().toggle_panel(getattr(self.window(), 'pl', None))
            return
        if TIME_RECT.contains(pos):        # toggle elapsed <-> remaining
            self._time_remaining = not self._time_remaining
            self.update()
            return
        if VIS.contains(pos):              # cycle visualizer mode
            self._vis_mode = (self._vis_mode + 1) % VIS_MODES
            self.update()
            return
        if getattr(self.window(), 'mode', 'modern') == 'classic':
            for label, cy in CLUTTER:      # clutterbar buttons
                if QRect(CLUTTER_X, cy, 8, 8).contains(pos):
                    self._clutter_action(label, event.globalPosition().toPoint())
                    return
        if SHUFFLE.contains(pos):
            self.ctl.toggle_shuffle()
            self.update()
            return
        if REPEAT.contains(pos):
            self.ctl.toggle_repeat()
            self.update()
            return
        name = self._button_at(pos)
        if name:
            self._pressed = name
            self.update()
            return
        if VOLUME.adjusted(0, -2, 0, 2).contains(pos):
            self._vol_dragging = True
            self._set_volume_from_x(pos.x())
            return
        if self.skin.has('balance.bmp') and BALANCE.adjusted(0, -2, 0, 2).contains(pos):
            self._bal_dragging = True
            self._set_balance_from_x(pos.x())
            return
        if self.ctl.seekable():
            bx, by, bar_w, bh = self._posbar_geom()
            if QRect(bx, by, bar_w, bh).adjusted(0, -2, 0, 2).contains(pos):
                self._seek_dragging = True
                self._seek_frac = self._seek_frac_from_x(pos.x())
                self.update()
                return
        if pos.y() < TITLEBAR[3]:   # drag the whole shell by the title bar
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()   # compositor-driven move (Wayland/X11)

    def mouseMoveEvent(self, event):
        if self._vol_dragging:
            self._set_volume_from_x((event.position() / self._scale()).x())
        elif self._bal_dragging:
            self._set_balance_from_x((event.position() / self._scale()).x())
        elif self._seek_dragging:
            self._seek_frac = self._seek_frac_from_x((event.position() / self._scale()).x())
            self.update()

    def mouseReleaseEvent(self, event):
        pos = event.position().toPoint()
        if self._pressed:
            if self._button_at(pos) == self._pressed:
                self._activate(self._pressed)
            self._pressed = None
            self.update()
        if self._seek_dragging:
            dur = self.ctl.query_duration()
            if dur:
                self.ctl.seek(int(self._seek_frac * dur))
            self._seek_dragging = False
            self.update()
        self._vol_dragging = False
        self._bal_dragging = False
        self._win_drag = None

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = (event.position() / self._scale()).toPoint()
        if pos.y() >= TITLEBAR[3]:
            return
        dx = self._dx()
        # Double-clicking the title bar (but not its buttons) toggles windowshade.
        for r in (MENU, CLOSE.translated(dx, 0), MINIMIZE.translated(dx, 0),
                  SHADE_BTN.translated(dx, 0)):
            if r.contains(pos):
                return
        self._toggle_shade()

    def _set_volume_from_x(self, x):
        frac = (x - VOLUME.x()) / max(1, VOLUME.width() - VOL_HANDLE_W)
        self._set_volume(frac)

    def _set_balance_from_x(self, x):
        frac = (x - BALANCE.x()) / max(1, BALANCE.width() - BAL_HANDLE_W)
        self._set_balance(frac * 2.0 - 1.0)

    def _seek_frac_from_x(self, x):
        bx, _y, bar_w, _h = self._posbar_geom()
        return min(1.0, max(0.0, (x - bx) / max(1, bar_w)))

    def _set_volume(self, frac):
        self._volume = min(1.0, max(0.0, frac))
        self.ctl.set_player_volume(self._volume)
        self.ctl.settings.set_double('volume', self._volume)
        self._show_readout(_('Volume: {}%').format(round(self._volume * 100)))
        self.update()

    def _set_balance(self, value):
        value = max(-1.0, min(1.0, value))
        if abs(value) < BAL_SNAP:      # dead-zone snap to dead-center
            value = 0.0
        self._balance = value
        self.ctl.set_player_balance(value)
        self.ctl.settings.set_double('balance', value)
        if value == 0.0:
            self._show_readout(_('Balance: center'))
        else:
            side = _('right') if value > 0 else _('left')
            self._show_readout(_('Balance: {}% {}').format(round(abs(value) * 100), side))
        self.update()

    def change_volume(self, delta):
        self._set_volume(self._volume + delta)

    def contextMenuEvent(self, event):
        self._show_menu(event.globalPos())   # right-click anywhere -> main menu

    def wheelEvent(self, event):
        self.window().wheelEvent(event)      # scroll -> volume (handled by the shell)

    def _activate(self, name):
        c = self.ctl
        if name == 'play':
            c.user_play()
        elif name == 'pause':
            c.user_pause()
        elif name == 'stop':
            c.stop()
        elif name == 'next':
            c.next_song()
        elif name == 'prev':
            c.prev_song()   # local playback only; no-op for Pandora
        elif name == 'eject':
            # Winamp's Eject loads a file; in local mode open files, otherwise
            # pop the station switcher below the eject button.
            if c.local_mode:
                c.open_local_files()
            else:
                s = self._scale()
                for n, dx, dy, w, h, *_ in BUTTONS:
                    if n == 'eject':
                        self._show_stations_menu(
                            self.mapToGlobal(QPoint(int(dx * s), int((dy + h) * s))))
                        break

    def _populate_stations(self, menu):
        """Fill a menu with the user's stations; picking one switches to it."""
        c = self.ctl
        rows = getattr(c, 'stations_model', None) or []
        if not rows:
            act = menu.addAction(_('(no stations loaded yet)'))
            act.setEnabled(False)
            return
        for station, name, index in rows:
            act = menu.addAction(name, lambda *a, s=station: c.station_changed(s))
            act.setCheckable(True)
            act.setChecked(station is c.current_station)

    def _show_stations_menu(self, global_pos):
        menu = QMenu(self)
        self._populate_stations(menu)
        menu.addSeparator()
        menu.addAction(_('Manage Stations…'), self.ctl.show_stations)
        menu.exec(global_pos)

    def _show_menu(self, global_pos):
        c = self.ctl
        menu = QMenu(self)
        # Source toggle: Pandora vs Local Playback. Open Files/Folder are only
        # offered in local mode; Stations only in Pandora mode.
        if c.local_mode:
            menu.addAction(_('Switch to Pandora'), c.switch_to_pandora)
            menu.addSeparator()
            menu.addAction(_('Open Files…'), c.open_local_files)
            menu.addAction(_('Open Folder…'), c.open_local_folder)
            menu.addAction(_('Open Playlist…'), c.open_playlist)
            save = menu.addAction(_('Save Playlist…'), c.save_playlist)
            save.setEnabled(len(c.songs_model) > 0)
        else:
            menu.addAction(_('Switch to Local Playback'), c.switch_to_local)
            menu.addSeparator()
            stations = menu.addMenu(_('Stations'))
            self._populate_stations(stations)
            stations.addSeparator()
            stations.addAction(_('Manage Stations…'), c.show_stations)
        menu.addSeparator()
        menu.addAction(_('Preferences…'), c.show_preferences)
        menu.addAction(_('About Pyrrha'), c.show_about)
        if not c.local_mode:
            menu.addSeparator()
            menu.addAction(_('Love'), lambda: c.love_song())
            menu.addAction(_('Ban'), lambda: c.ban_song())
            menu.addAction(_('Tired'), lambda: c.tired_song())
        menu.addSeparator()
        # Size (uniform scale) is a Classic-mode concern; Modern resizes by
        # widening for the album art instead.
        if getattr(self.window(), 'mode', 'modern') == 'classic':
            size = menu.addMenu(_('Size'))
            cur = getattr(self.window(), 'scale', 1)
            for label, sc in ((_('Normal (1x)'), 1.0), (_('1.5x'), 1.5), (_('Double (2x)'), 2.0)):
                a = size.addAction(label, lambda *args, v=sc: self.window().set_scale(v))
                a.setCheckable(True)
                a.setChecked(abs(cur - sc) < 0.01)
        # Skin loading is a Classic-mode concern (Modern is the enhanced view of
        # whatever skin is loaded).
        if getattr(self.window(), 'mode', 'modern') == 'classic':
            skin_menu = menu.addMenu(_('Skin'))
            skin_menu.addAction(_('Load Skin File…'), self._load_skin_file)
            skin_menu.addAction(_('Load Skin Folder…'), self._load_skin_folder)
            available = c.available_skins()
            if available:
                skin_menu.addSeparator()
                current_path = getattr(getattr(self.window(), 'skin', None), 'path', None)
                for name, path in available:
                    a = skin_menu.addAction(name, lambda *args, p=path: self.window().load_skin(p))
                    a.setCheckable(True)
                    a.setChecked(path == current_path)
        mode_menu = menu.addMenu(_('Mode'))
        shell = self.window()
        cur_mode = getattr(shell, 'mode', 'modern')
        cm = mode_menu.addAction(_('Classic Skins'), lambda: shell.set_mode('classic'))
        cm.setCheckable(True)
        cm.setChecked(cur_mode == 'classic')
        mm = mode_menu.addAction(_('Modern Skin'), lambda: shell.set_mode('modern'))
        mm.setCheckable(True)
        mm.setChecked(cur_mode == 'modern')
        mode_menu.addSeparator()
        mode_menu.addAction(_('Standard'), c.show_standard_view)
        menu.addSeparator()
        menu.addAction(_('Quit'), c.quit)
        menu.exec(global_pos)

    def _scale(self):
        return getattr(self.window(), 'scale', 1)

    def _lw(self):
        shell = self.window()
        if getattr(shell, 'mode', 'modern') == 'classic':
            return W                       # pinned native in classic mode
        return max(W, int(getattr(shell, 'content_w', W)))

    def _dx(self):
        return self._lw() - W

    def display_width(self):
        return int(self._lw() * self._scale())   # stretches to the shell width

    def display_height(self):
        h = TITLEBAR[3] if self._collapsed else H   # windowshade → title bar only
        return int(h * self._scale())

    def _toggle_shade(self):
        self._collapsed = not self._collapsed
        shell = self.window()
        if hasattr(shell, 'relayout'):
            shell.relayout()
        self.update()

    def closeEvent(self, event):
        # Only fires when used stand-alone; inside the shell the shell quits.
        self.ctl.quit()
        super().closeEvent(event)


class SkinnedShell(QWidget):
    """A single frameless window holding the main, EQ and playlist panels
    stacked vertically. This is the one window the user sees and moves. Panels
    can collapse (windowshade) or close; the shell reflows and resizes to fit."""

    def __init__(self, controller, skin, scale=1.0):
        super().__init__(None, Qt.FramelessWindowHint)
        self.ctl = controller
        self.scale = scale      # UI scale factor (1, 1.5, 2, …)
        self.content_w = W      # shared logical content width (all panels stretch to it)
        # 'modern': album-art widen + unified resize; 'classic': faithful Winamp
        # (main/EQ pinned native, playlist independently resizable).
        self.mode = controller.get_skin_mode() if hasattr(controller, 'get_skin_mode') else 'modern'
        self.keep_above = False   # clutterbar "A" (KWin keep-above)
        self._activated_at = 0.0  # when the window last became active (click-to-focus)
        # Classic mode uses the user's chosen skin; Modern always uses the
        # bundled Glare (the curated album-art experience).
        self._classic_skin = skin
        self._modern_skin = self._load_modern_skin() or skin
        self.skin = self._modern_skin if self.mode == 'modern' else self._classic_skin
        self.setWindowTitle('Pyrrha')
        # Accept keyboard focus so the shell receives key presses (used by the
        # classic "nullsoft" easter egg); no child panel takes focus.
        self.setFocusPolicy(Qt.StrongFocus)
        # Fills any area not covered by a panel (e.g. to the right of the
        # fixed-width main/EQ when the playlist is dragged wider).
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), Qt.black)
        self.setPalette(pal)

        self.main = SkinnedWindow(controller, self.skin, parent=self)
        self.eq = SkinnedEqWindow(controller, self.skin, parent=self) if self.skin.has('eqmain.bmp') else None
        self.pl = SkinnedPlaylistWindow(controller, self.skin, parent=self) if self.skin.has('pledit.bmp') else None
        self.relayout()

    def _load_modern_skin(self):
        """The bundled Glare skin used by Modern mode (or None if unavailable)."""
        try:
            from .skin import Skin
            if hasattr(self.ctl, 'bundled_skins_dir'):
                path = os.path.join(self.ctl.bundled_skins_dir(), 'Glare')
                if os.path.isdir(path):
                    return Skin(path)
        except Exception as e:
            logging.warning('Failed to load the bundled Modern (Glare) skin: %s', e)
        return None

    def _apply_skin(self, skin):
        self.skin = skin
        for panel in (self.main, self.eq, self.pl):
            if panel is not None:
                panel.set_skin(skin)

    def _max_content_w(self):
        # Classic mode never widens main/EQ (they stay native, 275px).
        if self.mode == 'classic':
            return W
        # When the EQ is present, the space to its right shows the album art;
        # cap the width so that area is at most a square (its height is the EQ
        # height, H), which bounds how far the window can be dragged.
        if self.eq is not None and not self.eq._closed:
            return W + H
        return WMAX

    def set_mode(self, mode):
        """Switch between 'classic' (faithful) and 'modern' (album-art) skins."""
        if mode not in ('classic', 'modern') or mode == self.mode:
            return
        self.mode = mode
        self.content_w = W
        if mode == 'modern':
            self.scale = 1.0     # Size is Classic-only; Modern runs at 1x
        # Modern always uses the bundled Glare; Classic uses the chosen skin.
        self._apply_skin(self._modern_skin if mode == 'modern' else self._classic_skin)
        if hasattr(self.ctl, 'set_skin_mode'):
            self.ctl.set_skin_mode(mode)
        self.relayout()
        self._repaint_panels()

    def relayout(self):
        panels = [p for p in (self.main, self.eq, self.pl)
                  if p is not None and not getattr(p, '_closed', False)]
        # Shared content width drives the stretchable panels (main + playlist)
        # and the album-art area beside the EQ. The shell grows to the widest
        # panel.
        self.content_w = max(W, min(self._max_content_w(), int(self.content_w)))
        shell_w = max((p.display_width() for p in panels), default=int(W * self.scale))
        y = 0
        for i, p in enumerate(panels):
            p._is_bottom = (i == len(panels) - 1)   # only the last panel has the grip
            p.setFixedSize(p.display_width(), p.display_height())
            p.move(0, y)
            p.setVisible(True)
            y += p.display_height()
        self.setFixedSize(shell_w, y)
        for p in panels:
            p.update()

    def set_content_width(self, logical_w):
        self.content_w = max(W, min(self._max_content_w(), int(logical_w)))
        self.relayout()

    def load_skin(self, path):
        """Load a skin for Classic mode (Modern always uses the bundled Glare)."""
        from .skin import Skin
        try:
            skin = Skin(path)
        except Exception as e:
            logging.warning('Failed to load skin %s: %s', path, e)
            return False
        if not skin.has('main.bmp'):
            logging.warning('Not a valid Winamp skin (no main.bmp): %s', path)
            return False
        self._classic_skin = skin
        if self.mode == 'classic':
            self._apply_skin(skin)
            self.relayout()
        self.ctl.set_last_skin(path)
        return True

    def wheelEvent(self, event):
        # Scroll anywhere over the window to change volume (classic Winamp).
        notches = event.angleDelta().y() / 120.0
        if notches and self.main is not None:
            self.main.change_volume(notches / 27.0)   # one 28-step slider notch
            event.accept()

    def keyPressEvent(self, event):
        # Feed keys to the classic "nullsoft" easter egg matcher.
        if self.main is not None and self.main.egg_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def toggle_width(self):
        """Widen the player to reveal the album art beside the EQ (a square),
        or collapse back to native width. Modern mode, EQ open."""
        if self.mode == 'classic' or self.eq is None or self.eq._closed:
            return
        self.set_content_width(W if self.content_w > W else W + H)

    def set_scale(self, scale):
        self.scale = max(1.0, min(4.0, scale))
        self.relayout()
        for panel in (self.main, self.eq, self.pl):
            if panel is not None:
                panel.update()

    def toggle_scale(self):
        self.set_scale(2 if self.scale == 1 else 1)

    def toggle_panel(self, panel):
        """Open a closed panel or close an open one (the main window's EQ/PL
        buttons and each panel's own close button share this state)."""
        if panel is None:
            return
        panel._closed = not panel._closed
        if panel._closed:
            panel.hide()
            if panel is self.pl:
                self.content_w = W   # collapse the player back to default width
        self.relayout()

    def _repaint_panels(self):
        for panel in (self.main, self.eq, self.pl):
            if panel is not None:
                panel.update()

    def showEvent(self, event):
        # Restoring from the tray (hidden -> shown) must repaint the panels, or
        # the album-art area can come back from a stale backing store.
        super().showEvent(event)
        self._repaint_panels()

    def changeEvent(self, event):
        # Same for un-minimizing (a window-state change, not a show event).
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and not self.isMinimized():
            self._repaint_panels()
        elif event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self._activated_at = time.monotonic()   # for click-to-focus

    def is_focus_click(self):
        """True if a click arriving now is the one that just activated the window
        (so controls shouldn't fire — the click only raises/focuses)."""
        if time.monotonic() - self._activated_at < 0.25:
            self._activated_at = 0.0
            return True
        return False

    def closeEvent(self, event):
        self.ctl.quit()
        super().closeEvent(event)
