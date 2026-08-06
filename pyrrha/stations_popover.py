# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Popup station chooser, the Qt analogue of Pithos' StationsPopover.

A frameless ``Qt.Popup`` frame containing a search field, an alphabetical-sort
toggle and the station list.  Selecting a row emits :attr:`station_selected`.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QToolButton, QVBoxLayout,
)

from .settings import get_settings


class StationsPopover(QFrame):
    station_selected = Signal(object)  # Station

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setFrameShape(QFrame.StyledPanel)
        self._settings = get_settings()
        # rows: list of (station, name, index)
        self._rows = []

        self.search = QLineEdit()
        self.search.setPlaceholderText(_('Search stations…'))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refilter)
        self.search.returnPressed.connect(self._on_search_activate)

        self.sort = QToolButton()
        self.sort.setText('A-Z')
        self.sort.setCheckable(True)
        self.sort.setToolTip(_('Sort stations alphabetically'))
        self.sort.setChecked(self._settings['sort-stations'])
        self.sort.toggled.connect(self._on_sort_toggled)

        top = QHBoxLayout()
        top.addWidget(self.search)
        top.addWidget(self.sort)

        self.listbox = QListWidget()
        self.listbox.setMinimumSize(240, 200)
        self.listbox.itemActivated.connect(self._on_item_activated)
        self.listbox.itemClicked.connect(self._on_item_activated)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(top)
        layout.addWidget(self.listbox)

    # -- data --------------------------------------------------------------
    def set_rows(self, rows):
        """rows: iterable of (station, name, index)."""
        self._rows = list(rows)
        self._rebuild()

    def clear(self):
        self._rows = []
        self.listbox.clear()

    def _sorted_rows(self):
        alpha = self.sort.isChecked()

        def key(row):
            station, name, index = row
            # QuickMix / Thumbprint are pinned to the top in their given order.
            pinned = 0 if (station.isQuickMix or station.isThumbprint) else 1
            if pinned == 0:
                return (0, index)
            if alpha:
                return (1, name.lower())
            return (1, index)

        return sorted(self._rows, key=key)

    def _rebuild(self):
        self.listbox.clear()
        text = self.search.text().lower()
        for station, name, index in self._sorted_rows():
            if not self._matches(name, text):
                continue
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, station)
            self.listbox.addItem(item)

    @staticmethod
    def _matches(name, search_text):
        if not search_text:
            return True
        lname = name.lower()
        if lname.startswith(search_text):
            return True
        return any(word.startswith(search_text) for word in lname.split())

    def select_station(self, station):
        for i in range(self.listbox.count()):
            item = self.listbox.item(i)
            if item.data(Qt.UserRole) is station:
                self.listbox.setCurrentItem(item)
                break

    # -- events ------------------------------------------------------------
    def _refilter(self, _text):
        self._rebuild()

    def _on_sort_toggled(self, checked):
        self._settings['sort-stations'] = checked
        self._rebuild()

    def _on_item_activated(self, item):
        station = item.data(Qt.UserRole)
        self.hide()
        self.search.clear()
        self.station_selected.emit(station)

    def _on_search_activate(self):
        if self.listbox.count():
            self._on_item_activated(self.listbox.item(0))

    def popup_at(self, button):
        # Anchor the popup just below the invoking button.
        below = button.mapToGlobal(button.rect().bottomLeft())
        self.adjustSize()
        self.move(below)
        self.show()
        self.search.setFocus()

    def toggle_visibility(self, button):
        if self.isVisible():
            self.hide()
        else:
            self.popup_at(button)
