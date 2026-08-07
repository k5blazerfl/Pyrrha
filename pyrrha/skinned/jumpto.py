# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Classic Winamp "Jump to File" (the 'J' shortcut).

A frameless, type-to-filter search over the current playlist. It borrows the
loaded skin's playlist colors (PLEDIT.TXT) so it reads as part of the skinned
shell rather than a stock Qt dialog — keeping the Winamp feel. Enter (or a
double-click) plays the highlighted track; Escape or clicking away dismisses it.
"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QLineEdit, QListWidget, QListWidgetItem,
                               QVBoxLayout)

# Fallbacks when the skin ships no PLEDIT.TXT (classic Winamp: green on black).
_DEF = {'normal': '#00FF00', 'current': '#FFFFFF',
        'bg': '#000000', 'sel': '#0000C6'}


def _hex(color, fallback):
    """A '#rrggbb' string from a QColor, or the fallback hex when unusable."""
    if isinstance(color, QColor) and color.isValid():
        return color.name()
    return fallback


def _theme_colors(shell):
    """(bg, fg, current, selected) from the live playlist panel's PLEDIT.TXT
    colors, falling back to classic Winamp green-on-black."""
    pl = getattr(shell, 'pl', None)
    return (_hex(getattr(pl, 'c_bg', None), _DEF['bg']),
            _hex(getattr(pl, 'c_normal', None), _DEF['normal']),
            _hex(getattr(pl, 'c_current', None), _DEF['current']),
            _hex(getattr(pl, 'c_sel', None), _DEF['sel']))


def _dialog_style(bg, fg, cur, sel):
    """Shared stylesheet so the jump dialogs read as part of the skin."""
    return (
        'QDialog {{ background: {bg}; border: 1px solid {fg}; }}'
        'QLineEdit {{ background: {bg}; color: {cur}; border: 1px solid {fg};'
        ' padding: 3px; selection-background-color: {sel}; }}'
        'QListWidget {{ background: {bg}; color: {fg}; border: none;'
        ' outline: none; }}'
        'QListWidget::item:selected {{ background: {sel}; color: {cur}; }}'
        .format(bg=bg, fg=fg, cur=cur, sel=sel))


def parse_time(text):
    """Parse 'ss', 'm:ss' or 'h:mm:ss' into whole seconds; None if unparseable."""
    text = (text or '').strip()
    if not text:
        return None
    try:
        parts = [int(p) for p in text.split(':')]
    except ValueError:
        return None
    if not parts or any(p < 0 for p in parts):
        return None
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


class JumpToFileDialog(QDialog):
    """Type-to-filter quick jump over the controller's song list."""

    def __init__(self, controller, shell):
        # Qt.Popup: Qt holds a mouse grab and dismisses on a click outside the
        # dialog itself, independent of compositor focus events (WindowDeactivate
        # is unreliable under KWin/Wayland). Same idiom menus/completers use.
        super().__init__(shell, Qt.Popup | Qt.FramelessWindowHint)
        self.ctl = controller
        self.shell = shell
        self._entries = []   # [(index, label, label_lower)] for the full list

        self.query = QLineEdit(self)
        self.query.setPlaceholderText(_('Jump to file…'))
        self.query.textChanged.connect(self._apply_filter)
        self.query.installEventFilter(self)   # steer Up/Down/Enter/Esc from it

        self.list = QListWidget(self)
        self.list.itemActivated.connect(lambda _i: self._accept())
        self.list.itemClicked.connect(lambda _i: self._accept())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(self.query)
        layout.addWidget(self.list)
        self.resize(480, 300)
        self._apply_theme()

    # ------------------------------------------------------------ theming
    def _apply_theme(self):
        self.setStyleSheet(_dialog_style(*_theme_colors(self.shell)))

    # ------------------------------------------------------------ data
    def _load_entries(self):
        model = self.ctl.songs_model
        self._entries = []
        for i in range(len(model)):
            song = model.song_at(i)
            if song is None:
                continue
            artist = (getattr(song, 'artist', '') or '').strip()
            title = (getattr(song, 'title', '') or '').strip() or _('(unknown)')
            label = '{} - {}'.format(artist, title) if artist else title
            self._entries.append((i, label, label.lower()))

    def _apply_filter(self, text):
        tokens = text.lower().split()
        self.list.clear()
        for index, label, lower in self._entries:
            if all(tok in lower for tok in tokens):
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, index)
                self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    # ------------------------------------------------------------ actions
    def popup(self):
        """(Re)load the list, clear the query, center over the shell and focus."""
        self._apply_theme()          # skin may have changed since last time
        self._load_entries()
        self.query.clear()
        self._apply_filter('')
        geo = self.shell.frameGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  geo.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()
        self.query.setFocus()

    def _accept(self):
        item = self.list.currentItem()
        if item is not None:
            self._play_index(item.data(Qt.UserRole))
        self.close()

    def _play_index(self, index):
        """Play the chosen row. Pandora can't rewind, so there we only jump to a
        track ahead of the current one; local playback can jump anywhere."""
        c = self.ctl
        cur = getattr(c, 'current_song_index', None)
        if getattr(c, 'local_mode', False) or cur is None or index > cur:
            c.start_song(index)

    # ------------------------------------------------------------ events
    def eventFilter(self, obj, event):
        # Route list navigation / accept / dismiss while the query has focus.
        if obj is self.query and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Escape:
                self.close()
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._accept()
                return True
            if key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown):
                self._move_selection(key)
                return True
        return super().eventFilter(obj, event)

    def _move_selection(self, key):
        count = self.list.count()
        if not count:
            return
        row = self.list.currentRow()
        page = max(1, self.list.height() // max(1, self.list.sizeHintForRow(0)))
        step = {Qt.Key_Up: -1, Qt.Key_Down: 1,
                Qt.Key_PageUp: -page, Qt.Key_PageDown: page}[key]
        self.list.setCurrentRow(min(count - 1, max(0, row + step)))


class JumpToTimeDialog(QDialog):
    """Classic Winamp 'Jump to Time' (Ctrl+J): type m:ss and seek there."""

    def __init__(self, controller, shell):
        super().__init__(shell, Qt.Popup | Qt.FramelessWindowHint)
        self.ctl = controller
        self.shell = shell
        self.query = QLineEdit(self)
        self.query.setPlaceholderText(_('Jump to time (m:ss)…'))
        self.query.returnPressed.connect(self._accept)
        self.query.installEventFilter(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.query)
        self.setFixedWidth(220)
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(_dialog_style(*_theme_colors(self.shell)))

    def popup(self):
        self._apply_theme()
        self.query.clear()
        self.adjustSize()
        geo = self.shell.frameGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  geo.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()
        self.query.setFocus()

    def _accept(self):
        secs = parse_time(self.query.text())
        if secs is not None and self.ctl.seekable():
            self.ctl.seek(int(secs * 1_000_000_000))
        self.close()

    def eventFilter(self, obj, event):
        if (obj is self.query and event.type() == QEvent.KeyPress
                and event.key() == Qt.Key_Escape):
            self.close()
            return True
        return super().eventFilter(obj, event)
