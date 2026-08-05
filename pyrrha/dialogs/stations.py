# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Stations management dialog, the Qt port of StationsDialog.

Lists user stations (excluding QuickMix / Thumbprint) with inline rename and a
QuickMix membership checkbox, plus add (via search), delete, listen and refresh.
Rename / delete / QuickMix-save all go through the shared worker.
"""

import html
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QMenu, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .search import SearchDialog


class StationsDialog(QDialog):
    station_renamed = Signal(object)
    station_added = Signal(object)
    station_removed = Signal(object)

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Stations'))
        self.window = window
        self.worker_run = window.worker_run
        self.quickmix_changed = False
        self._search_dialog = None
        self._loading = False

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([_('Name'), _('In QuickMix')])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemDoubleClicked.connect(self._on_double_clicked)

        add_btn = QPushButton(_('Add…'))
        add_btn.clicked.connect(self._add_station)
        refresh_btn = QPushButton(_('Refresh'))
        refresh_btn.clicked.connect(lambda: self.window.refresh_stations())
        close_btn = QPushButton(_('Close'))
        close_btn.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(add_btn)
        buttons.addWidget(refresh_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        self.resize(420, 400)

        self.reload()

    # -- populate ----------------------------------------------------------
    def reload(self):
        self._loading = True
        self.table.setRowCount(0)
        for station, name, index in self.window.station_rows():
            if station.isQuickMix or station.isThumbprint:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)

            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.UserRole, station)
            name_item.setFlags(name_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 0, name_item)

            qm_item = QTableWidgetItem()
            qm_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            qm_item.setCheckState(Qt.Checked if station.useQuickMix else Qt.Unchecked)
            self.table.setItem(row, 1, qm_item)
        self._loading = False

    def _selected_station(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    # -- edits -------------------------------------------------------------
    def _on_item_changed(self, item):
        if self._loading:
            return
        station = self.table.item(item.row(), 0).data(Qt.UserRole)
        if item.column() == 1:
            station.useQuickMix = item.checkState() == Qt.Checked
            self.quickmix_changed = True
        elif item.column() == 0:
            self._rename_station(station, item)

    def _rename_station(self, station, item):
        new_text = item.text()
        old_name = station.name
        if new_text == old_name:
            return

        def errorback(e):
            if hasattr(e, 'status') and e.status == 1008:
                QMessageBox.warning(
                    self, _('Could Not Rename {}').format(old_name),
                    _('Pandora does not permit renaming {}.').format(old_name),
                )
            else:
                logging.warning(getattr(e, 'traceback', e))
            self._loading = True
            item.setText(old_name)
            self._loading = False

        def success(*ignore):
            station.name = new_text
            self.station_renamed.emit((station.id, new_text))
            self.window.on_station_renamed(station, new_text)

        self.worker_run(
            station.rename, (new_text,), callback=success, errorback=errorback,
            context='net', message=_('Renaming Station…'),
        )

    def _on_double_clicked(self, item):
        if item.column() == 0:
            return  # allow inline edit
        station = self.table.item(item.row(), 0).data(Qt.UserRole)
        self.window.station_changed(station)
        self.accept()

    # -- context menu ------------------------------------------------------
    def _show_context_menu(self, pos):
        station = self._selected_station()
        if station is None:
            return
        menu = QMenu(self)
        listen = menu.addAction(_('Listen Now'))
        info = menu.addAction(_('Station Info…'))
        rename = menu.addAction(_('Rename…'))
        delete = menu.addAction(_('Delete…'))
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == listen:
            self.window.station_changed(station)
            self.accept()
        elif action == info:
            self.window.open_url(station.info_url)
        elif action == rename:
            self.table.editItem(self.table.item(self.table.currentRow(), 0))
        elif action == delete:
            self._delete_station(station)

    def _delete_station(self, station):
        reply = QMessageBox.question(
            self, _('Delete Station'),
            _('Are you sure you want to delete the station "{}"?').format(station.name),
        )
        if reply != QMessageBox.Yes:
            return
        self.worker_run(station.delete, context='net', message=_('Deleting Station…'))
        self.window.remove_station(station)
        if self.window.current_station is station and self.window.station_rows():
            self.window.station_changed(self.window.station_rows()[0][0])
        self.station_removed.emit(station)
        self.reload()

    # -- add ---------------------------------------------------------------
    def _add_station(self):
        dialog = SearchDialog(self.worker_run, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        result = dialog.result
        if result is None:
            return
        if result.resultType == 'song':
            description = _('{title} by {artist}').format(title=result.title, artist=result.artist)
        elif result.resultType == 'artist':
            description = result.name
        else:
            description = result.stationName
        user_data = (result.resultType, description)
        self.worker_run(
            'add_station_by_music_id', (result.musicId,),
            self._station_added, _('Creating station…'), user_data=user_data,
        )

    def _station_added(self, station, user_data):
        self.window.on_station_added(station, user_data, source=self)

    def closeEvent(self, event):
        if self.quickmix_changed:
            self.worker_run('save_quick_mix', message=_('Saving QuickMix…'))
            self.quickmix_changed = False
        super().closeEvent(event)

    def accept(self):
        if self.quickmix_changed:
            self.worker_run('save_quick_mix', message=_('Saving QuickMix…'))
            self.quickmix_changed = False
        super().accept()
