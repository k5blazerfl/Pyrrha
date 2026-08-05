# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Preferences dialog, the Qt port of PreferencesPithosDialog.

Two tabs:

* **Account** — email/password, audio quality, proxy settings and the
  explicit-content filter. Values live in Pyrrha's GSettings schema; the
  password goes through libsecret.
* **Plugins** — a row per loaded plugin with an on/off toggle bound to that
  plugin's ``enabled`` GSetting (the Qt analogue of Pithos' ``PithosPluginRow``),
  plus a per-plugin *Configure…* button when the plugin exposes a settings
  dialog. Plugins that failed to load are shown disabled with the error as a
  tooltip.
"""

import logging

from gi.repository import Gio

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QComboBox, QMessageBox, QPushButton, QScrollArea,
    QTabWidget, QVBoxLayout, QWidget,
)

from .. import SETTINGS_SCHEMA
from ..keyring import SecretService

try:
    import pacparser
except ImportError:
    pacparser = None

_QUALITY_LABELS = [
    (_('Low'), 'lowQuality'),
    (_('Medium'), 'mediumQuality'),
    (_('High'), 'highQuality'),
]


class PluginRow(QFrame):
    """One plugin's row: name + description, an on/off toggle, and (if the
    plugin provides one) a Configure button. Mirrors Pithos' PithosPluginRow."""

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self._friendly_name = plugin.name.title().replace('_', ' ')

        name = QLabel('<b>{}</b>'.format(self._friendly_name))
        desc = QLabel(plugin.description or '')
        desc.setWordWrap(True)
        desc.setStyleSheet('color: palette(mid);')
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(name)
        text.addWidget(desc)

        self.config_btn = QPushButton(_('Configure…'))
        self.config_btn.clicked.connect(self._on_configure)
        self.config_btn.setVisible(plugin.preferences_dialog is not None)

        self.toggle = QCheckBox()
        self.toggle.setChecked(bool(plugin.settings and plugin.settings['enabled']))
        self.toggle.toggled.connect(self._on_toggled)

        layout = QHBoxLayout(self)
        layout.addLayout(text, 1)
        layout.addWidget(self.config_btn)
        layout.addWidget(self.toggle)

        # Reflect enable-state changes made elsewhere (e.g. a plugin disabling
        # itself on error). GSettings 'changed' fires via the pumped context.
        if plugin.settings is not None:
            plugin.settings.connect('changed::enabled', self._on_settings_changed)

        self._apply_error_state()

    def _apply_error_state(self):
        if self.plugin.prepared and self.plugin.error:
            self.setEnabled(False)
            self.setToolTip(str(self.plugin.error))
        else:
            self.setEnabled(True)
            self.setToolTip('')

    def _on_toggled(self, checked):
        if self.plugin.settings is not None:
            self.plugin.settings['enabled'] = checked
        if checked:
            self.plugin.enable()
        else:
            self.plugin.disable()
        # enable() may fail synchronously (or asynchronously, caught via the
        # settings-changed handler); reflect any error immediately too.
        self._apply_error_state()
        self.config_btn.setVisible(self.plugin.preferences_dialog is not None)

    def _on_settings_changed(self, settings, key):
        enabled = settings['enabled']
        self.toggle.blockSignals(True)
        self.toggle.setChecked(enabled)
        self.toggle.blockSignals(False)
        self._apply_error_state()

    def _on_configure(self):
        dialog = self.plugin.preferences_dialog
        if dialog is not None:
            dialog.setParent(self.window(), Qt.Dialog)
            dialog.show()


class PreferencesDialog(QDialog):
    login_changed = Signal(object)  # (email, password)
    applied = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Preferences'))
        self.setModal(True)
        self._settings = Gio.Settings.new(SETTINGS_SCHEMA)
        self._last_email = ''
        self._last_password = None
        self._plugin_rows = []

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_account_tab(), _('Account'))
        self._plugins_container, plugins_tab = self._build_plugins_tab()
        self.tabs.addTab(plugins_tab, _('Plugins'))

        self.buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.apply_btn = self.buttons.button(QDialogButtonBox.Apply)
        self.apply_btn.clicked.connect(self._on_apply)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(self.buttons)
        self.resize(420, 360)

    # -- account tab -------------------------------------------------------
    def _build_account_tab(self):
        self.email_entry = QLineEdit()
        self.password_entry = QLineEdit()
        self.password_entry.setEchoMode(QLineEdit.Password)

        self.quality_combo = QComboBox()
        for label, value in _QUALITY_LABELS:
            self.quality_combo.addItem(label, value)

        self.proxy_entry = QLineEdit()
        self.control_proxy_entry = QLineEdit()
        self.control_proxy_pac_entry = QLineEdit()
        if not pacparser:
            self.control_proxy_pac_entry.setEnabled(False)
            self.control_proxy_pac_entry.setToolTip(_('Please install python-pacparser'))

        self.explicit_filter_check = QCheckBox(_('Explicit Content Filter'))
        self.explicit_filter_check.setEnabled(False)
        self.explicit_filter_check.setTristate(True)

        form = QFormLayout()
        form.addRow(_('Email:'), self.email_entry)
        form.addRow(_('Password:'), self.password_entry)
        form.addRow(_('Audio quality:'), self.quality_combo)
        form.addRow(_('Proxy:'), self.proxy_entry)
        form.addRow(_('Control proxy:'), self.control_proxy_entry)
        form.addRow(_('Control proxy PAC:'), self.control_proxy_pac_entry)
        form.addRow('', self.explicit_filter_check)

        self.email_entry.textChanged.connect(self._update_apply_sensitivity)
        self.password_entry.textChanged.connect(self._update_apply_sensitivity)

        tab = QWidget()
        tab.setLayout(form)
        return tab

    # -- plugins tab -------------------------------------------------------
    def _build_plugins_tab(self):
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.addStretch(1)  # keeps rows pinned to the top

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        scroll.setFrameShape(QFrame.NoFrame)
        return container, scroll

    def set_plugins(self, plugins):
        """Populate the Plugins tab. Called by the loader once plugins exist."""
        layout = self._plugins_container.layout()
        # Clear any existing rows (keep the trailing stretch).
        for row in self._plugin_rows:
            row.setParent(None)
        self._plugin_rows = []

        for name in sorted(plugins):
            plugin = plugins[name]
            row = PluginRow(plugin)
            self._plugin_rows.append(row)
            layout.insertWidget(layout.count() - 1, row)
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet('color: palette(midlight);')
            layout.insertWidget(layout.count() - 1, sep)
            self._plugin_rows.append(sep)

    # -- lifecycle ---------------------------------------------------------
    def load(self):
        self._last_email = self._settings['email']
        self.email_entry.setText(self._last_email)
        self.proxy_entry.setText(self._settings['proxy'])
        self.control_proxy_entry.setText(self._settings['control-proxy'])
        self.control_proxy_pac_entry.setText(self._settings['control-proxy-pac'])

        quality = self._settings['audio-quality']
        idx = self.quality_combo.findData(quality)
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)

        def got_password(password):
            self._last_password = password
            self.password_entry.setText(password)
            self._update_apply_sensitivity()

        SecretService.get_account_password(self._last_email, got_password)
        self._update_apply_sensitivity()

    def _update_apply_sensitivity(self, *ignore):
        ok = bool(self.email_entry.text()) and bool(self.password_entry.text())
        self.apply_btn.setEnabled(ok)

    # -- explicit content filter (driven by the window) --------------------
    def set_filter_unknown(self):
        self.explicit_filter_check.setText(_('Explicit Content Filter'))
        self.explicit_filter_check.setEnabled(False)
        self.explicit_filter_check.setCheckState(Qt.PartiallyChecked)

    def set_filter_state(self, state, pin_protected):
        self.explicit_filter_check.setTristate(False)
        self.explicit_filter_check.setChecked(state)
        if pin_protected:
            self.explicit_filter_check.setText(_('Explicit Content Filter - PIN Protected'))
            self.explicit_filter_check.setEnabled(False)
        else:
            self.explicit_filter_check.setEnabled(True)

    def explicit_filter_checked(self):
        return self.explicit_filter_check.isChecked()

    # -- apply -------------------------------------------------------------
    def _write_plain_settings(self):
        self._settings['proxy'] = self.proxy_entry.text()
        self._settings['control-proxy'] = self.control_proxy_entry.text()
        self._settings['control-proxy-pac'] = self.control_proxy_pac_entry.text()
        self._settings['audio-quality'] = self.quality_combo.currentData()

    def _on_apply(self):
        email = self.email_entry.text()
        password = self.password_entry.text()
        self._write_plain_settings()

        def stored(success):
            if not success:
                QMessageBox.warning(
                    self, _('Failed to Store Your Pandora Credentials'),
                    _('Please re-enter your email and password.'))
                return
            self._settings['email'] = email
            self._last_email, self._last_password = email, password
            self.login_changed.emit((email, password))
            self.applied.emit()
            self.hide()

        if self._last_email != email or self._last_password != password:
            SecretService.set_account_password(self._last_email, email, password, stored)
        else:
            self.applied.emit()
            self.hide()
