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

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QMenu, QWidget

from .font import CHAR_H, CHAR_W, TextFont

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

# Miniplayer in the bottom-right corner (all coords relative to that corner's
# origin at x = width-150, y = height-FRAME_B). Verified against the base/Bento/
# Winamp3/Winamp5 skins: a title strip on top, a transport row + time below.
MP_TITLE = (7, 10, 89)                   # current-song title strip (x, y, max width)
MP_COLON_X = 83                          # corner x of the skin's baked time ':' (gap)
MP_CLOCK_Y = 23                          # clock digit baseline y (in the corner)
MP_BTN_Y, MP_BTN_H = 24, 13              # transport button row (y band)
MP_BTNS = (('prev', 4, 10), ('play', 14, 10), ('pause', 24, 10),
           ('stop', 34, 10), ('next', 44, 11), ('eject', 55, 13))

# Up/down list-scroll arrows baked into the bottom-right corner sprite (classic
# PLEDIT), right of the LIST button. Corner-relative coords (origin =
# (width-150, height-FRAME_B)); measured from the base 2.91 skin's pledit.bmp.
PL_SCROLL_X, PL_SCROLL_W = 132, 14
PL_SCROLL_UP = (0, 7)                    # up arrow: (y, height)
PL_SCROLL_DN = (7, 7)                    # down arrow: (y, height)


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

        self._apply_pledit_theme(skin)
        self._text_font = TextFont(skin)   # bitmap font for the miniplayer, as the main window
        self._collapsed = False
        self._closed = False
        self._resizing = False
        self._cursor_name = False   # region cursor currently set (False = unknown)
        self._height = H          # logical height (resizable); width is never dragged
        self._scroll = 0          # top visible row when browsing manually
        self._follow = True       # auto-scroll to keep the current song visible
        self._sb_drag = None      # scrollbar thumb drag: cursor-to-thumb-top offset
        self._selection = set()   # selected rows (multi-select), distinct from playing
        self._focus = None        # row the keyboard acts on / scrolls to
        self._anchor = None       # anchor row for shift-range selection
        self._press_row = None    # row pressed (candidate for drag-to-reorder)
        self._press_pos = None    # press position (to detect drag threshold)
        self._deferred_select = None  # single-select this row on release if no drag
        self._reorder = False     # a drag-to-reorder is in progress
        self._drop_index = None   # insertion index shown while reordering
        self._mp_scroll = 0       # miniplayer title marquee offset
        self._mp_pressed = None   # transport button currently shown pressed
        self._mp_colon = None     # detected baked-':' x in the clock slot (cached)
        self._drag_scroll_dir = 0  # edge auto-scroll direction while reordering
        self._drag_last_y = 0     # last cursor y (for auto-scroll drop tracking)

        # Marquee tick for the miniplayer title (only repaints while it scrolls).
        self._mp_timer = QTimer(self)
        self._mp_timer.timeout.connect(self._mp_tick)
        self._mp_timer.start(220)
        # Edge auto-scroll while dragging a row near the list's top/bottom.
        self._drag_scroll_timer = QTimer(self)
        self._drag_scroll_timer.setInterval(120)
        self._drag_scroll_timer.timeout.connect(self._drag_scroll_tick)
        # Bottom-right corner scroll arrows: held state + auto-repeat.
        self._scroll_btn_held = None      # 'up'/'down' while an arrow is held
        self._scroll_btn_timer = QTimer(self)
        self._scroll_btn_timer.timeout.connect(self._scroll_btn_tick)

        # A new song re-enables follow so the view snaps to what's now playing;
        # between songs the user can scroll the list freely.
        controller.song_changed.connect(self._on_song_changed)
        # Repaint on any model change — additions (songs_added covers the
        # asynchronous Pandora fill) and, crucially, clears/resets (e.g.
        # switching to Local Playback empties the list).
        controller.songs_added.connect(lambda *_: self.update())
        model = controller.songs_model
        model.rowsInserted.connect(lambda *_: self.update())
        model.rowsRemoved.connect(lambda *_: self.update())
        model.modelReset.connect(self._on_model_reset)

    def set_skin(self, skin):
        self.skin = skin
        self._cursor_name = False
        self.unsetCursor()
        self._apply_pledit_theme(skin)
        self._text_font = TextFont(skin)
        self._mp_colon = None
        self.update()

    def _cursor_for(self, pos):
        if not self._collapsed and self._grip_rect().contains(pos):
            return 'psize.cur'          # bottom-right resize corner
        return None

    def _update_cursor(self, pos):
        if not self.skin.has_cursors:
            return
        name = self._cursor_for(pos)
        if name == self._cursor_name:
            return
        self._cursor_name = name
        cur = self.skin.cursor(name) if name else None
        self.setCursor(cur) if cur is not None else self.unsetCursor()

    def _apply_pledit_theme(self, skin):
        """Load the playlist colors and font from the skin's PLEDIT.TXT (with
        classic-Winamp fallbacks). Font is the skin's face name at the fixed
        classic list size; falls back to monospace when unspecified."""
        cfg = self._parse_pledit(skin.text('pledit.txt'))
        self.c_normal = _color(cfg.get('normal'), DEFAULTS['normal'])
        self.c_current = _color(cfg.get('current'), DEFAULTS['current'])
        self.c_bg = _color(cfg.get('normalbg'), DEFAULTS['normalbg'])
        self.c_sel = _color(cfg.get('selectedbg'), DEFAULTS['selectedbg'])
        family = cfg.get('font', '').strip().strip('"')
        self._font = QFont(family) if family else QFont('monospace')
        self._font.setPixelSize(9)

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
        # PLEDIT.TXT is INI-like: colors are #RRGGBB (or bare RRGGBB) and Font is
        # a face name, so capture every key=value pair (section headers and
        # comments don't match); _color / the font loader validate their own.
        out = {}
        for line in text.splitlines():
            m = re.match(r'\s*(\w+)\s*=\s*(.+?)\s*$', line)
            if m:
                out[m.group(1).lower()] = m.group(2).strip()
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

    def _on_song_changed(self, *ignore):
        self._follow = True
        self._mp_scroll = 0     # restart the mini title marquee for the new song
        self.update()

    def _on_model_reset(self, *ignore):
        self._selection = set()  # a new list (e.g. station switch) clears selection
        self._focus = self._anchor = None
        self.update()

    def _capacity(self):
        """How many rows fit in the list area at the current height."""
        bottom = FRAME_B if self._frame_on() else 6
        return max(1, (self._lh() - bottom - LIST_TOP) // ROW_H)

    def _max_start(self, count=None):
        if count is None:
            count = len(self._rows())
        return max(0, count - self._capacity())

    def _visible_range(self, count):
        """The [start, end) rows to draw. While following, keep the current song
        visible; otherwise honour the manual scroll offset. Either way ``_scroll``
        is left holding the current top row so scroll actions can build on it."""
        cap = self._capacity()
        maxstart = max(0, count - cap)
        if self._follow:
            cur = self.ctl.current_song_index or 0
            start = 0
            if count > cap and cur >= cap - 1:
                start = max(0, min(cur - cap // 2, maxstart))
        else:
            start = min(self._scroll, maxstart)
        self._scroll = max(0, start)
        return self._scroll, min(count, self._scroll + cap)

    def _scroll_to(self, start):
        self._follow = False
        self._scroll = max(0, min(self._max_start(), int(start)))
        self.update()

    def _scroll_by(self, delta_rows):
        self._scroll_to(self._scroll + delta_rows)

    def _scroll_button_at(self, pos):
        """'up'/'down' if ``pos`` is over the bottom-right corner scroll arrows,
        else None. The arrows are baked into the corner sprite (classic PLEDIT),
        so they're always drawn when the frame is shown — this makes them live."""
        if not self._frame_on() or self._collapsed:
            return None
        cx, cy = self._lw() - 150, self._lh() - FRAME_B
        lx, ly = pos.x() - cx, pos.y() - cy
        if not (PL_SCROLL_X <= lx < PL_SCROLL_X + PL_SCROLL_W):
            return None
        if PL_SCROLL_UP[0] <= ly < PL_SCROLL_UP[0] + PL_SCROLL_UP[1]:
            return 'up'
        if PL_SCROLL_DN[0] <= ly < PL_SCROLL_DN[0] + PL_SCROLL_DN[1]:
            return 'down'
        return None

    def _press_scroll_button(self, which):
        """Scroll one row now, then auto-repeat while the arrow is held."""
        self._scroll_btn_held = which
        self._scroll_by(-1 if which == 'up' else 1)
        self._scroll_btn_timer.start(300)   # initial delay; _tick speeds it up
        self.update()

    def _scroll_btn_tick(self):
        if self._scroll_btn_held is None:
            self._scroll_btn_timer.stop()
            return
        self._scroll_btn_timer.setInterval(70)   # fast repeat after the first delay
        self._scroll_by(-1 if self._scroll_btn_held == 'up' else 1)

    def _sb_geom(self):
        """Scrollbar as (thumb_rect, track_top, track_h) in logical px for the
        current scroll position, or None when no scrollbar is shown."""
        if not self._frame_on() or self._collapsed:
            return None
        lh, w = self._lh(), self._lw()
        maxstart = self._max_start()
        track_top = TITLE_H + 1
        thumb_w, thumb_h = SB_THUMB[2], SB_THUMB[3]
        track_h = max(0, lh - FRAME_B - track_top - thumb_h)
        frac = (self._scroll / maxstart) if maxstart else 0.0
        thumb_y = track_top + int(frac * track_h)
        return QRect(w - FRAME_R + 2, thumb_y, thumb_w, thumb_h), track_top, track_h

    # ------------------------------------------------------- keyboard / actions
    def handle_key(self, event):
        """Handle a playlist navigation key; return True if consumed. Called by
        the shell (which keeps focus) so arrows/Page/Home/End/Enter/Delete work."""
        if self._collapsed:
            return False
        count = len(self._rows())
        if count == 0:
            return False
        key = event.key()
        ext = bool(event.modifiers() & Qt.ShiftModifier)   # Shift extends selection
        base = self._focus if self._focus is not None else (self.ctl.current_song_index or 0)
        cap = self._capacity()
        if key == Qt.Key_Up:
            self._select(base - 1, extend=ext)
        elif key == Qt.Key_Down:
            self._select(base + 1, extend=ext)
        elif key == Qt.Key_PageUp:
            self._select(base - cap, extend=ext)
        elif key == Qt.Key_PageDown:
            self._select(base + cap, extend=ext)
        elif key == Qt.Key_Home:
            self._select(0, extend=ext)
        elif key == Qt.Key_End:
            self._select(count - 1, extend=ext)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self._play_focus()
        elif key in (Qt.Key_Delete, Qt.Key_Backspace):
            # Static list (local files / radio favourites): delete the rows.
            # Pandora: the queue is read-only, so Del instead marks the selected
            # upcoming songs to be skipped.
            if getattr(self.ctl, 'static_playlist', False):
                self._remove_selection()
            else:
                self._toggle_skip_selected()
        else:
            return False
        return True

    def _select(self, idx, extend=False, toggle=False):
        """Update the selection for a row and scroll it into view. ``extend``
        (Shift) selects the range from the anchor; ``toggle`` (Ctrl) flips the
        row; otherwise it becomes the sole selection."""
        count = len(self._rows())
        if count == 0:
            return
        idx = max(0, min(count - 1, int(idx)))
        if toggle:
            self._selection ^= {idx}
            self._anchor = idx
        elif extend and self._anchor is not None:
            lo, hi = sorted((self._anchor, idx))
            self._selection = set(range(lo, hi + 1))
        else:
            self._selection = {idx}
            self._anchor = idx
        self._focus = idx
        self._follow = False
        cap = self._capacity()
        if idx < self._scroll:
            self._scroll = idx
        elif idx >= self._scroll + cap:
            self._scroll = idx - cap + 1
        self._scroll = max(0, min(self._scroll, self._max_start()))
        self.update()

    def _play_focus(self):
        if self._focus is None:
            return
        idx, cur = self._focus, self.ctl.current_song_index
        if getattr(self.ctl, 'static_playlist', False) or (cur is not None and idx > cur):
            self.ctl.start_song(idx, jump=True)

    def _remove_selection(self):
        if not self._selection or not getattr(self.ctl, 'static_playlist', False):
            return
        rows = sorted(self._selection)
        self.ctl.remove_songs(rows)
        first = rows[0]
        count = len(self._rows())
        self._selection = {min(first, count - 1)} if count else set()
        self._focus = self._anchor = (min(first, count - 1) if count else None)
        self.update()

    def _crop_to_selection(self):
        if not self._selection or not getattr(self.ctl, 'static_playlist', False):
            return
        keep = self._selection
        drop = [i for i in range(len(self._rows())) if i not in keep]
        self.ctl.remove_songs(drop)
        self._selection = set(range(len(self._rows())))
        self._focus = self._anchor = 0 if self._rows() else None
        self.update()

    def _select_all(self):
        self._selection = set(range(len(self._rows())))
        self.update()

    def _select_none(self):
        self._selection = set()
        self.update()

    def _invert_selection(self):
        self._selection = set(range(len(self._rows()))) - self._selection
        self.update()

    def _skip_selection(self, value):
        """Mark/unmark the selected songs to be skipped when advancing."""
        rows = sorted(self._selection)
        if rows and hasattr(self.ctl, 'set_songs_skip'):
            self.ctl.set_songs_skip(rows, value)
            self.update()

    def _skippable_selection(self):
        """Selected rows eligible for preemptive skip: only those ahead of the
        current song. The playing song can't be skipped mid-stream and songs
        behind the playhead won't recur, so both are excluded."""
        cur = self.ctl.current_song_index
        return sorted(i for i in self._selection if cur is None or i > cur)

    def _skip_selected_songs(self, value=True):
        """Mark (or unmark) the eligible selected upcoming songs to be skipped
        when advancing. Backs both the Del key and the Rem-button menu."""
        rows = self._skippable_selection()
        if rows and hasattr(self.ctl, 'set_songs_skip'):
            self.ctl.set_songs_skip(rows, value)
            self.update()

    def _toggle_skip_selected(self):
        """Flip the skip mark on the eligible selected upcoming songs. With a
        key there's no menu to disambiguate a mixed selection, so any still-
        queued song means 'skip all'; only an all-skipped selection un-skips."""
        skipped, unskipped = self._skippable_skip_split()
        if skipped or unskipped:
            self._skip_selected_songs(not unskipped)

    def _skippable_skip_split(self):
        """Split the skippable selection into (skipped, unskipped) row lists by
        their current skip mark — used to decide whether Rem can toggle outright
        or must offer both choices."""
        songs = self._rows()
        skipped, unskipped = [], []
        for i in self._skippable_selection():
            (skipped if getattr(songs[i], 'skip', False) else unskipped).append(i)
        return skipped, unskipped

    def _dim(self, c):
        """Blend a text colour halfway to the background — a faded 'skipped' look
        that works on both light and dark skins."""
        b = self.c_bg
        return QColor((c.red() + b.red()) // 2, (c.green() + b.green()) // 2,
                      (c.blue() + b.blue()) // 2)

    def _clear_playlist(self):
        if getattr(self.ctl, 'local_mode', False):
            self.ctl.clear_playlist()
            self._selection = set()
            self._focus = self._anchor = None
            self.update()

    # ---------------------------------------------------- bottom button bar
    def _bottom_button_at(self, pos):
        """Which bottom-bar button (add/rem/sel/misc/list) is at ``pos``, or None.
        Regions match the classic PLEDIT corner sprites (4 buttons left, List
        right)."""
        if not self._frame_on():
            return None
        lh, w = self._lh(), self._lw()
        by = lh - FRAME_B
        if not (by + 4 <= pos.y() <= by + 32):
            return None
        for name, x0 in (('add', 11), ('rem', 40), ('sel', 69), ('misc', 98)):
            if x0 <= pos.x() < x0 + 24:
                return name
        if w - 46 <= pos.x() < w - 20:
            return 'list'
        return None

    def _show_bottom_menu(self, btn, gpos):
        c = self.ctl
        local = getattr(c, 'local_mode', False)
        radio = getattr(c, 'is_radio', False)
        static = getattr(c, 'static_playlist', False)
        have_sel = bool(self._selection)
        # Pandora Rem acts as a plain skip toggle: with a uniform selection
        # (all skipped or all not) one click flips it, no menu. Only a mixed
        # selection — some already skipped, some still queued — needs the menu
        # to disambiguate which way to go. Static lists get a real remove menu.
        if btn == 'rem' and not static:
            skipped, unskipped = self._skippable_skip_split()
            if not (skipped and unskipped):
                if skipped or unskipped:
                    self._skip_selected_songs(not skipped)
                return
        m = QMenu(self)
        if btn == 'add':
            if local:
                m.addAction(_('Add Files…'), c.open_local_files)
                m.addAction(_('Add Folder…'), c.open_local_folder)
            elif radio:
                m.addAction(_('Add Stations…'), c.show_radio)
                m.addSeparator()
                m.addAction(_('Switch to Pandora'), c.switch_to_pandora)
                m.addAction(_('Switch to Local Playback'), c.switch_to_local)
            else:
                a = m.addAction(_('Get More Songs'), c.fetch_more_songs)
                a.setEnabled(getattr(c, 'current_station', None) is not None)
                m.addSeparator()
                m.addAction(_('Switch to Local Playback'), c.switch_to_local)
        elif btn == 'rem':
            if static:
                a = m.addAction(_('Remove Selected'), self._remove_selection)
                a.setEnabled(have_sel)
                a = m.addAction(_('Crop (keep selected)'), self._crop_to_selection)
                a.setEnabled(have_sel)
                if local:
                    a = m.addAction(_('Remove Missing Files'), self._remove_missing)
                    a.setEnabled(len(self._rows()) > 0)
                    a = m.addAction(_('Remove All'), self._clear_playlist)
                    a.setEnabled(len(self._rows()) > 0)
            else:
                # Only reached for a mixed selection (some songs already marked
                # to skip, some still queued); a uniform selection is toggled
                # outright above without a menu.
                m.addAction(_('Skip Selected'), lambda: self._skip_selected_songs(True))
                m.addAction(_('Don’t Skip Selected'), lambda: self._skip_selected_songs(False))
        elif btn == 'sel':
            m.addAction(_('Select All'), self._select_all)
            m.addAction(_('Select None'), self._select_none)
            m.addAction(_('Invert Selection'), self._invert_selection)
        elif btn == 'misc':
            srt = m.addMenu(_('Sort List'))
            srt.setEnabled(local and len(self._rows()) > 1)
            srt.addAction(_('By Title'), lambda: c.sort_songs('title'))
            srt.addAction(_('By Artist'), lambda: c.sort_songs('artist'))
            srt.addAction(_('Reverse'), lambda: c.sort_songs('reverse'))
            srt.addAction(_('Randomize'), lambda: c.sort_songs('random'))
            a = m.addAction(_('Scan ReplayGain'), c.scan_replaygain_local)
            a.setEnabled(local and len(self._rows()) > 0)
        elif btn == 'list':
            a = m.addAction(_('New Playlist'), self._clear_playlist)
            a.setEnabled(local)
            a = m.addAction(_('Load Playlist…'), c.open_playlist)
            a.setEnabled(local)
            a = m.addAction(_('Save Playlist…'), c.save_playlist)
            a.setEnabled(len(self._rows()) > 0)
        if m.actions():
            m.exec(gpos)

    def _scroll_to_current(self):
        self._follow = True     # re-enable follow: the next paint centres on it
        self.update()

    def _remove_missing(self):
        """Drop rows whose file is gone (delegates to the controller)."""
        if self.ctl.remove_missing_local():
            self._selection = set()
            self._focus = self._anchor = None
            self.update()

    def _reveal(self, song):
        """Open the containing folder of a local track in the file manager."""
        import os
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        path = getattr(song, 'path', '')
        if not path:
            return
        folder = os.path.dirname(os.path.abspath(path))
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

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
            if i in self._selection:             # selection highlight
                p.fillRect(row, self.c_sel)
            mark = RATING_MARK.get(self.ctl.song_icon(song), '')
            text = '{}. {} - {}{}'.format(i + 1, song.artist, song.title, mark)
            skip = getattr(song, 'skip', False)   # marked to be skipped when advancing
            color = self.c_current if i == cur else self.c_normal   # playing = Current
            if skip:
                color = self._dim(color)
            p.setPen(color)
            dur = int(song.get_duration_sec() or 0) if hasattr(song, 'get_duration_sec') else 0
            time_str = _fmt_time(dur) if dur > 0 else ''
            time_w = 42 if time_str else 0
            # Title clipped to leave room for the right-aligned duration.
            p.drawText(row.adjusted(4, 0, -6 - time_w, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
            if time_str:
                p.drawText(row.adjusted(0, 0, -4, 0), Qt.AlignVCenter | Qt.AlignRight, time_str)
            if skip:                              # strikethrough = will be skipped
                my = y + ROW_H // 2
                p.drawLine(li + 4, my, w - li - ri - 6 - time_w, my)
            y += ROW_H

        # Drag-to-reorder: insertion line at the drop position.
        if self._reorder and self._drop_index is not None:
            iy = LIST_TOP + (self._drop_index - start) * ROW_H
            list_bottom = lh - (bi if frame else 6)
            iy = max(LIST_TOP, min(list_bottom, iy))
            p.setPen(self.c_current)
            p.drawLine(li + 3, iy, w - ri - 3, iy)
            p.drawLine(li + 3, iy - 1, w - ri - 3, iy - 1)

        # Miniplayer (current title + total time) in the bottom-right corner.
        if frame:
            self._paint_miniplayer(p, w, lh, songs, cur)

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
        # Scrollbar thumb on the right border (position from the current scroll).
        self._visible_range(len(self._rows()))   # sync _scroll for _sb_geom
        sb = self._sb_geom()
        if sb is not None:
            thumb = sb[0]
            p.drawImage(thumb.x(), thumb.y(), sk.sprite('pledit.bmp', *SB_THUMB))

    def _mp_title_text(self, songs=None, cur=None):
        """The miniplayer's title text (current song), or '' when nothing plays."""
        if cur is None:
            cur = self.ctl.current_song_index
        if songs is None:
            songs = self._rows()
        if cur is not None and 0 <= cur < len(songs) and songs[cur] is not None:
            song = songs[cur]
            return '{}. {} - {}'.format(cur + 1, song.artist, song.title)
        return ''

    def _mp_tick(self):
        """Advance the mini title marquee, repainting only while it overflows."""
        if not self.isVisible() or self._collapsed or not self._frame_on():
            if self._mp_scroll:
                self._mp_scroll = 0
            return
        if len(self._mp_title_text()) * CHAR_W > MP_TITLE[2]:
            self._mp_scroll += 1
            self.update()
        elif self._mp_scroll:
            self._mp_scroll = 0
            self.update()

    def _paint_miniplayer(self, p, w, lh, songs, cur):
        """The bottom-right mini display, drawn in the skin's bitmap TEXT font
        (matching the main window): the current song's title in the strip, and
        the playlist's total time as digits straddling the skin's baked ':'
        (so we draw no ':' of our own). The transport glyphs are baked into the
        corner sprite; _mini_transport_at makes them clickable."""
        cx, cy = w - 150, lh - FRAME_B
        # Title marquee in the TEXT font (scrolls when it overflows the strip).
        text = self._mp_title_text(songs, cur)
        if text:
            tx, ty, tw = MP_TITLE
            p.save()
            p.setClipRect(cx + tx, cy + ty, tw, CHAR_H)
            if len(text) * CHAR_W > tw:                       # overflows -> marquee
                img = self._text_font.render(text + '   ***   ')
                span = img.width()
                off = self._mp_scroll % span
                p.drawImage(cx + tx - off, cy + ty, img)
                p.drawImage(cx + tx - off + span, cy + ty, img)   # wrap-around copy
            else:
                p.drawImage(cx + tx, cy + ty, self._text_font.render(text))
            p.restore()
        # Total time: minutes right of the transport, seconds after the baked ':'.
        total = sum(int(s.get_duration_sec() or 0) for s in songs if s is not None)
        if total > 0:
            gap, y = cx + self._mp_colon_x(), cy + MP_CLOCK_Y
            x = gap - 2
            for ch in reversed(str(total // 60)):     # MM… right-aligned to the ':'
                x -= CHAR_W
                p.drawImage(x, y, self._text_font.render(ch))
            x = gap + 3
            for ch in '%02d' % (total % 60):          # SS left-aligned after the ':'
                p.drawImage(x, y, self._text_font.render(ch))
                x += CHAR_W
        # Pressed-state feedback for the mini transport (a subtle darken; the
        # glyphs are baked, so there is no skin-supplied pressed sprite).
        if self._mp_pressed:
            for name, bx, bw in MP_BTNS:
                if name == self._mp_pressed:
                    p.fillRect(cx + bx, cy + MP_BTN_Y, bw, MP_BTN_H, QColor(0, 0, 0, 90))
                    break
        # Same subtle darken for a held scroll arrow.
        if self._scroll_btn_held is not None:
            ry, rh = PL_SCROLL_UP if self._scroll_btn_held == 'up' else PL_SCROLL_DN
            p.fillRect(cx + PL_SCROLL_X, cy + ry, PL_SCROLL_W, rh, QColor(0, 0, 0, 90))

    def _mp_colon_x(self):
        """The x of the skin's baked time ':' (corner coords), detected once and
        cached; falls back to the standard position. Skins leave the ':' as the
        lone small feature in the empty time slot, so we take the centroid of the
        non-background pixels there when it's a tight, sensibly-placed cluster."""
        if self._mp_colon is not None:
            return self._mp_colon
        colon = MP_COLON_X
        s = self.skin.sprite('pledit.bmp', 126, 72, 150, 38)
        if not s.isNull():
            def lum(c):
                return (c.red() + c.green() + c.blue()) // 3
            y0, y1 = MP_CLOCK_Y + 1, MP_CLOCK_Y + 8
            bg = lum(s.pixelColor(64, MP_CLOCK_Y + 4))   # slot background near the left
            cols = [x for x in range(62, 106)
                    if any(abs(lum(s.pixelColor(x, y)) - bg) > 45 for y in range(y0, y1))]
            if cols and (max(cols) - min(cols)) <= 8:
                centre = sum(cols) / len(cols)
                if 68 <= centre <= 98:
                    colon = round(centre)
        self._mp_colon = colon
        return self._mp_colon

    def _mini_transport_at(self, pos):
        """Which mini-transport button (prev/play/pause/stop/next/eject) is at
        ``pos``, or None."""
        if not self._frame_on():
            return None
        cx, cy = self._lw() - 150, self._lh() - FRAME_B
        if not (cy + MP_BTN_Y <= pos.y() <= cy + MP_BTN_Y + MP_BTN_H):
            return None
        for name, bx, bw in MP_BTNS:
            if cx + bx <= pos.x() < cx + bx + bw:
                return name
        return None

    def _do_transport(self, name):
        c = self.ctl
        {'prev': c.prev_song, 'play': c.user_play, 'pause': c.pause,
         'stop': c.stop, 'next': c.next_song,
         'eject': c.open_local_files}.get(name, lambda: None)()

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
        if idx is not None:
            cur = self.ctl.current_song_index
            # Static playlists can start any track; Pandora can only go forward.
            if self.ctl.static_playlist or (cur is not None and idx > cur):
                self.ctl.start_song(idx, jump=True)

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
        # Scrollbar: grab the thumb, or page up/down by clicking the track.
        sb = self._sb_geom()
        if sb is not None:
            thumb, track_top, track_h = sb
            if pos.x() >= self._lw() - FRAME_R and track_top <= pos.y() < track_top + track_h + thumb.height():
                # Stop auto-follow immediately so a repaint mid-interaction (the
                # marquee/now-playing timers fire often) can't snap the thumb
                # back to the now-playing row out from under the cursor.
                self._follow = False
                if thumb.contains(pos):
                    self._sb_drag = pos.y() - thumb.y()
                    # Grab the mouse for the drag: under the classic overlay's
                    # masked, translucent top-level the implicit press-grab may
                    # not deliver the move events, so grab explicitly.
                    self.grabMouse()
                elif pos.y() < thumb.y():
                    self._scroll_by(-self._capacity())
                else:
                    self._scroll_by(self._capacity())
                return
        # Bottom-right corner scroll arrows (up/down, baked into the sprite).
        sbtn = self._scroll_button_at(pos)
        if sbtn is not None:
            self._press_scroll_button(sbtn)
            return
        # Bottom-bar buttons (Add / Rem / Sel / Misc / List).
        btn = self._bottom_button_at(pos)
        if btn is not None:
            self._show_bottom_menu(btn, event.globalPosition().toPoint())
            return
        # Miniplayer transport buttons (bottom-right corner).
        mt = self._mini_transport_at(pos)
        if mt is not None:
            self._mp_pressed = mt      # show it pressed until release
            self.update()
            self._do_transport(mt)
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
            return
        # Click in the list selects the row (Ctrl toggles, Shift extends a range).
        idx = self._song_index_at(pos.y())
        if idx is not None:
            mods = event.modifiers()
            shift = bool(mods & Qt.ShiftModifier)
            ctrl = bool(mods & Qt.ControlModifier)
            if getattr(self.ctl, 'static_playlist', False) and not shift and not ctrl:
                # Static list: prepare a possible drag-to-reorder. Keep an existing
                # multi-selection (so it can be dragged); otherwise select this row.
                self._press_row = idx
                self._press_pos = QPoint(pos)
                if idx in self._selection:
                    self._deferred_select = idx   # collapse to just this row on click-release
                else:
                    self._select(idx)
                    self._deferred_select = None
            else:
                self._select(idx, extend=shift, toggle=ctrl)

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
        # Act on the existing selection if the row is in it; otherwise select it.
        if idx not in self._selection:
            self._select(idx)
        else:
            self._focus = idx
            self.update()
        song = songs[idx]
        c = self.ctl
        menu = QMenu(self)
        if c.local_mode:
            menu.addAction(_('Play'), self._play_focus)
            menu.addAction(_('Edit Tags…') + '\tAlt+3', lambda: c.edit_local_tags(song))
            rem = menu.addAction(_('Remove Selected'), self._remove_selection)
            rem.setEnabled(bool(self._selection))
            rev = menu.addAction(_('Reveal in File Manager'), lambda: self._reveal(song))
            rev.setEnabled(bool(getattr(song, 'path', '')))
        elif getattr(c, 'is_radio', False):
            menu.addAction(_('Play'), self._play_focus)
            rem = menu.addAction(_('Remove Selected'), self._remove_selection)
            rem.setEnabled(bool(self._selection))
            if getattr(song, 'songDetailURL', ''):
                menu.addAction(_('Station Homepage'),
                               lambda: c.open_url(song.songDetailURL))
        else:
            icon = c.song_icon(song)
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
            menu.addSeparator()
            menu.addAction(_('Song Information'), lambda: c.info_song(song=song))
        # Preemptive skip: playback jumps over marked songs when advancing.
        menu.addSeparator()
        if getattr(song, 'skip', False):
            menu.addAction(_('Don’t Skip'), lambda: self._skip_selection(False))
        else:
            menu.addAction(_('Skip'), lambda: self._skip_selection(True))
        if c.current_song_index is not None:
            menu.addSeparator()
            menu.addAction(_('Scroll to Now Playing'), self._scroll_to_current)
        menu.exec(event.globalPos())

    def mouseMoveEvent(self, event):
        if getattr(self, '_titledrag', False):
            self.window().free_drag_move(self, event.globalPosition().toPoint())
            return
        if self._sb_drag is not None:
            sb = self._sb_geom()
            if sb is not None:
                _thumb, track_top, track_h = sb
                py = (event.position() / self._scale()).toPoint().y()
                frac = ((py - self._sb_drag - track_top) / track_h) if track_h else 0.0
                self._scroll_to(round(frac * self._max_start()))
            return
        if self._press_row is not None and (event.buttons() & Qt.LeftButton):
            pos = (event.position() / self._scale()).toPoint()
            if not self._reorder and (pos - self._press_pos).manhattanLength() > 4:
                self._reorder = True     # crossed the threshold -> start reordering
                if self._press_row not in self._selection:
                    self._select(self._press_row)
                self._deferred_select = None
            if self._reorder:
                self._drag_last_y = pos.y()
                self._drop_index = self._drop_index_at(pos.y())
                self._update_edge_autoscroll(pos.y())
                self.update()
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
            return
        self._update_cursor((event.position() / self._scale()).toPoint())

    def mouseReleaseEvent(self, event):
        if self._mp_pressed:                       # release the mini-transport button
            self._mp_pressed = None
            self.update()
        if self._scroll_btn_held is not None:      # release a held scroll arrow
            self._scroll_btn_held = None
            self._scroll_btn_timer.stop()
            self.update()
        if getattr(self, '_titledrag', False):
            self._titledrag = False
            self.window().end_free_drag()
            return
        if self._reorder:
            rows = sorted(self._selection)
            if rows and self._drop_index is not None and hasattr(self.ctl, 'move_songs'):
                new_start = self.ctl.move_songs(rows, self._drop_index)
                if new_start is not None:
                    self._selection = set(range(new_start, new_start + len(rows)))
                    self._focus = self._anchor = new_start
            self._reset_drag()
            self.update()
            return
        if self._press_row is not None:
            # A plain click without a drag: collapse a kept multi-selection.
            if self._deferred_select is not None:
                self._select(self._deferred_select)
            self._reset_drag()
        if self._sb_drag is not None:
            self.releaseMouse()          # end the scrollbar-drag mouse grab
        self._sb_drag = None
        self._resizing = False

    def _drop_index_at(self, y):
        """Insertion index (0..count) for a drop at cursor y."""
        count = len(self._rows())
        start, _end = self._visible_range(count)
        rel = y - LIST_TOP
        if rel < 0:
            return start
        row = start + rel // ROW_H
        if rel % ROW_H > ROW_H // 2:      # lower half -> insert after
            row += 1
        return max(0, min(count, row))

    def _reset_drag(self):
        self._press_row = self._press_pos = self._deferred_select = None
        self._reorder = False
        self._drop_index = None
        self._drag_scroll_dir = 0
        self._drag_scroll_timer.stop()

    def _update_edge_autoscroll(self, y):
        """Start/stop edge auto-scroll: dragging within a row of the list's top
        or bottom scrolls the list so you can drop beyond the visible rows."""
        top = LIST_TOP
        bottom = self._lh() - (FRAME_B if self._frame_on() else 6)
        if y < top + ROW_H:
            self._drag_scroll_dir = -1
        elif y > bottom - ROW_H:
            self._drag_scroll_dir = 1
        else:
            self._drag_scroll_dir = 0
        if self._drag_scroll_dir and not self._drag_scroll_timer.isActive():
            self._drag_scroll_timer.start()
        elif not self._drag_scroll_dir and self._drag_scroll_timer.isActive():
            self._drag_scroll_timer.stop()

    def _drag_scroll_tick(self):
        if not self._reorder or not self._drag_scroll_dir:
            self._drag_scroll_timer.stop()
            return
        before = self._scroll
        self._scroll_by(self._drag_scroll_dir)
        if self._scroll != before:        # actually moved -> update the drop marker
            self._drop_index = self._drop_index_at(self._drag_last_y)
            self.update()

    def wheelEvent(self, event):
        # Over a scrollable list the wheel scrolls it; otherwise fall through to
        # the shell's volume wheel (classic Winamp behavior).
        if not self._collapsed and len(self._rows()) > self._capacity():
            notches = event.angleDelta().y() / 120.0
            self._scroll_by(int(round(-notches * 3)))   # 3 rows per notch
            event.accept()
        else:
            self.window().wheelEvent(event)
