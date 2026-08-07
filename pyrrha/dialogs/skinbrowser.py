# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""The Winamp-style skin browser (Alt+S): a grid of live main.bmp thumbnails;
click one to apply it to the classic view instantly."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout,
)

from ..skinned.skin import Skin

THUMB = QSize(160, 68)   # ~ the 275x116 main window, halved


class SkinBrowser(QDialog):
    def __init__(self, shell, controller, parent=None):
        super().__init__(parent)
        self.shell = shell
        self.ctl = controller
        self._thumbs = {}   # path -> QPixmap (or None)
        self.setWindowTitle(_('Skins'))
        self.resize(440, 400)

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(THUMB)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(10)
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(True)
        self.list.itemClicked.connect(self._apply_item)
        layout.addWidget(self.list)

        row = QHBoxLayout()
        b_file = QPushButton(_('Load File…'))
        b_file.clicked.connect(self._load_file)
        b_dir = QPushButton(_('Load Folder…'))
        b_dir.clicked.connect(self._load_folder)
        close = QPushButton(_('Close'))
        close.clicked.connect(self.close)
        row.addWidget(b_file)
        row.addWidget(b_dir)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)

        self.reload()

    def reload(self):
        """Repopulate the grid and highlight the skin currently in use."""
        self.list.clear()
        current = getattr(getattr(self.shell, 'skin', None), 'path', None)
        skins = self.ctl.available_skins() if hasattr(self.ctl, 'available_skins') else []
        for name, path in skins:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, path)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            pm = self._thumb(path)
            if pm is not None:
                item.setIcon(QIcon(pm))
            self.list.addItem(item)
            if path == current:
                self.list.setCurrentItem(item)

    def _thumb(self, path):
        if path not in self._thumbs:
            pm = None
            try:
                img = Skin(path).image('main.bmp')
                if not img.isNull():
                    pm = QPixmap.fromImage(img).scaled(
                        THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            except Exception:
                pm = None
            self._thumbs[path] = pm
        return self._thumbs[path]

    def _apply(self, path):
        if not path:
            return
        # Picking a Winamp skin implies the classic look — switch to it so the
        # skin is actually visible (Modern always uses the bundled Glare).
        if getattr(self.shell, 'mode', None) != 'classic' and hasattr(self.shell, 'set_mode'):
            self.shell.set_mode('classic')
        self.shell.load_skin(path)

    def _apply_item(self, item):
        self._apply(item.data(Qt.UserRole))

    def _load_file(self):
        path, _sel = QFileDialog.getOpenFileName(
            self, _('Load Winamp Skin'), self.ctl.skins_dir(),
            _('Winamp skins (*.wsz *.zip);;All files (*)'))
        if path:
            self._apply(path)
            self.reload()

    def _load_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, _('Load Skin Folder'), self.ctl.skins_dir())
        if path:
            self._apply(path)
            self.reload()
