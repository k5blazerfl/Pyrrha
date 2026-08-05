# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Search-for-a-seed dialog, the Qt port of SearchDialog.

Runs a Pandora ``search`` through the shared worker and lets the user pick a
song / artist / genre result.  ``result`` holds the chosen item once accepted.
"""

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)


class SearchDialog(QDialog):
    def __init__(self, worker_run, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Add Station'))
        self.setModal(True)
        self._worker_run = worker_run
        self.query = ''
        self.result = None

        self.entry = QLineEdit()
        self.entry.setPlaceholderText(_('Search for music…'))
        self.entry.returnPressed.connect(self._search_clicked)
        search_btn = QPushButton(_('Search'))
        search_btn.clicked.connect(self._search_clicked)

        top = QHBoxLayout()
        top.addWidget(self.entry)
        top.addWidget(search_btn)

        self.listbox = QListWidget()
        self.listbox.itemSelectionChanged.connect(self._cursor_changed)
        self.listbox.itemDoubleClicked.connect(lambda *_: self._accept_if_valid())

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_btn = self.buttons.button(QDialogButtonBox.Ok)
        self.ok_btn.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.listbox)
        layout.addWidget(self.buttons)

    def _search_clicked(self):
        self.search(self.entry.text())

    def search(self, query):
        self.query = query
        self.listbox.clear()
        if not query:
            return

        def callback(results):
            self.listbox.clear()
            if not self.query:
                return
            for i in results:
                if i.resultType == 'song':
                    text = _('{title} by {artist}').format(
                        title=i.title, artist=i.artist)
                elif i.resultType == 'artist':
                    text = _('{name} (artist)').format(name=i.name)
                elif i.resultType == 'genre':
                    text = _('{name} (genre)').format(name=i.stationName)
                else:
                    continue
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, i)
                self.listbox.addItem(item)

        self._worker_run('search', (query,), callback, _('Searching…'))

    def _cursor_changed(self):
        items = self.listbox.selectedItems()
        self.result = items[0].data(Qt.UserRole) if items else None
        self.ok_btn.setEnabled(self.result is not None)

    def _accept_if_valid(self):
        if self.result is not None:
            self.accept()
