# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QVBoxLayout,
)

from ..appicon import app_icon


class AboutDialog(QDialog):
    def __init__(self, version, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('About Pyrrha'))
        self.setModal(True)

        layout = QVBoxLayout(self)

        icon = app_icon()
        if not icon.isNull():
            logo = QLabel()
            logo.setPixmap(icon.pixmap(96, 96))
            logo.setAlignment(Qt.AlignCenter)
            layout.addWidget(logo)

        title = QLabel('<h2>Pyrrha</h2>')
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        body = QLabel(
            _('A Qt port of Pithos — a native Pandora Radio client.') +
            '<br>' + _('Version') + ' ' + version +
            '<br><br>' + _('Pyrrha is not affiliated with or endorsed by Pandora Media, Inc.') +
            '<br><a href="https://pithos.github.io">pithos.github.io</a>'
        )
        body.setAlignment(Qt.AlignCenter)
        body.setOpenExternalLinks(True)
        body.setTextFormat(Qt.RichText)
        layout.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
