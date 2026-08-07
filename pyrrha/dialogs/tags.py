# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""A small tag editor for local files (the editable half of ``Alt+3``).

Reads and writes tags through :mod:`pyrrha.local`, which uses mutagen's portable
Easy interface. On save it also updates the in-memory ``LocalSong`` so the
playlist and skinned display refresh without a re-scan.
"""

import os

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox,
    QVBoxLayout,
)

from .. import local

# Field key -> display label, in order.
_FIELDS = [
    ('title', _('Title')),
    ('artist', _('Artist')),
    ('album', _('Album')),
    ('albumartist', _('Album Artist')),
    ('tracknumber', _('Track #')),
    ('genre', _('Genre')),
    ('date', _('Year')),
    ('comment', _('Comment')),
]


class TagEditorDialog(QDialog):
    """Edit a local file's tags. ``on_saved(song)`` runs after a successful
    write so the caller can refresh the row/display."""

    def __init__(self, song, on_saved=None, parent=None):
        super().__init__(parent)
        self.song = song
        self._on_saved = on_saved
        self.setWindowTitle(_('Edit Tags'))
        self.setModal(True)

        self._edits = {}
        form = QFormLayout()
        current = local.read_tags(song.path) or {}
        for key, label in _FIELDS:
            edit = QLineEdit(current.get(key, ''))
            self._edits[key] = edit
            form.addRow(label + ':', edit)

        path_label = QLabel(os.path.basename(song.path))
        path_label.setStyleSheet('color: palette(mid);')
        path_label.setToolTip(song.path)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(path_label)
        layout.addWidget(buttons)
        self.resize(380, 0)

    def _save(self):
        values = {k: e.text().strip() for k, e in self._edits.items()}
        if not local.write_tags(self.song.path, values):
            QMessageBox.warning(
                self, _('Edit Tags'),
                _('Could not write tags to this file.'))
            return
        # Reflect the edits on the in-memory song so the UI updates immediately.
        self.song.title = values.get('title') or self.song.title
        self.song.artist = values.get('artist') or self.song.artist
        self.song.album = values.get('album') or self.song.album
        if self._on_saved is not None:
            self._on_saved(self.song)
        self.accept()
