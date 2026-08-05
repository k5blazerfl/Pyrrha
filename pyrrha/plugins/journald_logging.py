# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Ported from Pithos' plugins/journald_logging.py (C) 2016 Jason Gray.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Send Pyrrha's logs to the systemd journal.

Requires the ``systemd`` Python module; if it is missing the plugin disables
itself (and shows the reason in Preferences → Plugins). The *Configure…* dialog
picks the level, persisted to the plugin's ``data`` GSetting.
"""

import logging

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout,
)

from .. import APP_ID
from ..plugin import PyrrhaPlugin

LOG_LEVELS = {
    'debug': logging.DEBUG,
    'verbose': logging.INFO,
    'warning': logging.WARN,
}


class JournalLoggingPlugin(PyrrhaPlugin):
    preference = 'journald-logging'
    description = 'Store logs with the journald service'

    def on_prepare(self):
        try:
            from systemd.journal import JournalHandler
        except ImportError:
            self.prepare_complete(error='Systemd Python module not found')
            return
        self._journal = JournalHandler(SYSLOG_IDENTIFIER=APP_ID)
        self._journal.setFormatter(logging.Formatter())
        self._logger = logging.getLogger()
        self._settings_conn = None
        self.preferences_dialog = LoggingPrefsDialog(self.window, self.settings)
        self.prepare_complete()

    def on_enable(self):
        self._apply_level(self.settings['data'] or 'verbose')
        self._logger.addHandler(self._journal)
        # Level changes are made by the Configure dialog writing 'data'.
        self._settings_conn = self.settings.connect(
            'changed::data', lambda *a: self._apply_level(self.settings['data'] or 'verbose'))

    def on_disable(self):
        if self._settings_conn is not None:
            self.settings.disconnect(self._settings_conn)
            self._settings_conn = None
        self._logger.removeHandler(self._journal)

    def _apply_level(self, level):
        self._journal.setLevel(LOG_LEVELS.get(level, logging.INFO))
        logging.info('journald logging level set to: {}'.format(level))


class LoggingPrefsDialog(QDialog):
    _LEVELS = [
        ('debug', 'High — debug'),
        ('verbose', 'Default — verbose'),
        ('warning', 'Low — warning'),
    ]

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(_('Logging Level'))
        self.setModal(True)

        label = QLabel(_('Set the journald logging level for Pyrrha'))
        self.combo = QComboBox()
        for value, text in self._LEVELS:
            self.combo.addItem(text, value)
        self._reset_combo()

        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        buttons.rejected.connect(self._cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.combo)
        layout.addWidget(buttons)

    def _reset_combo(self):
        idx = self.combo.findData(self.settings['data'] or 'verbose')
        if idx >= 0:
            self.combo.setCurrentIndex(idx)

    def _apply(self):
        level = self.combo.currentData()
        if level == self.settings['data']:
            self.hide()
            return
        if level == 'debug':
            reply = QMessageBox.warning(
                self, _('Debug Logging Level'),
                _('The debug logging level generates very large logs and is only '
                  'recommended while debugging an issue.\n\nSet logging to debug?'),
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self.settings['data'] = level
        self.hide()

    def _cancel(self):
        self._reset_combo()
        self.hide()
