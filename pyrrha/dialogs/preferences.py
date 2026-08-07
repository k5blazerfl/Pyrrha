# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Preferences dialog, the Qt port of PreferencesPithosDialog.

A Winamp-style left-nav layout: a category list on the left selects a page on
the right.

* **Account** — Pandora email/password (password via libsecret) and the
  explicit-content filter.
* **Audio** — streaming quality.
* **Network** — proxy / control-proxy / PAC settings.
* **Plugins** — a row per loaded plugin with an on/off toggle bound to that
  plugin's ``enabled`` GSetting, plus a per-plugin *Configure…* button when the
  plugin exposes a settings dialog. Plugins that failed to load are shown
  disabled with the error as a tooltip.
* **About** — version and project/attribution links.

The window drives this dialog only through its methods and signals
(``load``/``set_plugins``/``set_filter_state``/``explicit_filter_checked`` and
``login_changed``/``applied``), so the internal layout is free to change.
"""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QComboBox, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import __version__
from ..settings import get_settings
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

# Proper display names for the plugins (str.title() mangles MPRIS, Last.fm, …).
_PLUGIN_NAMES = {
    'mpris': 'MPRIS',
    'mediakeys': _('Media Keys'),
    'notify': _('Notifications'),
    'notification_icon': _('Tray Icon'),
    'equalizer': _('Equalizer'),
    'lastfm': 'Last.fm',
    'inhibit_screensaver': _('Screensaver Inhibit'),
    'screensaver_pause': _('Screensaver Pause'),
    'auto_volume_normalization': _('ReplayGain Normalization'),
    'journald_logging': _('Journald Logging'),
}


def _friendly_plugin_name(name):
    return _PLUGIN_NAMES.get(name, name.title().replace('_', ' '))


class PluginRow(QFrame):
    """One plugin's row: name + description, an on/off toggle, and (if the
    plugin provides one) a Configure button."""

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self._friendly_name = _friendly_plugin_name(plugin.name)

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
        # itself on error).
        if plugin.settings is not None:
            plugin.settings.changed.connect(self._on_settings_changed)

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

    def _on_settings_changed(self, key):
        if key != 'enabled':
            return
        enabled = self.plugin.settings['enabled']
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
        self._settings = get_settings()
        self._last_email = ''
        self._last_password = None
        self._plugin_rows = []

        # Left-nav (category list) + right-hand stacked pages.
        self.nav = QListWidget()
        self.nav.setObjectName('prefsNav')
        self.nav.setMaximumWidth(150)
        self.nav.setSpacing(1)
        self.stack = QStackedWidget()
        self._add_page(_('Account'), 'preferences-desktop-user', self._build_account_page())
        self._add_page(_('Audio'), 'audio-card', self._build_audio_page())
        self._add_page(_('Network'), 'preferences-system-network', self._build_network_page())
        self._add_page(_('Plugins'), 'preferences-plugin', self._build_plugins_page())
        self._add_page(_('About'), 'help-about', self._build_about_page())
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        body = QHBoxLayout()
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)

        # OK (apply + close), Apply (apply + stay), Cancel (discard + close).
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.ok_btn = self.buttons.button(QDialogButtonBox.Ok)
        self.apply_btn = self.buttons.button(QDialogButtonBox.Apply)
        self.ok_btn.clicked.connect(lambda: self._apply(close_after=True))
        self.apply_btn.clicked.connect(lambda: self._apply(close_after=False))
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(self.buttons)
        self.resize(560, 420)

    def _add_page(self, label, icon_name, widget):
        icon = QIcon.fromTheme(icon_name)
        if icon.isNull():
            self.nav.addItem(label)
        else:
            self.nav.addItem(QListWidgetItem(icon, label))
        self.stack.addWidget(widget)

    # -- account page ------------------------------------------------------
    def _build_account_page(self):
        self.email_entry = QLineEdit()
        self.password_entry = QLineEdit()
        self.password_entry.setEchoMode(QLineEdit.Password)

        # Show/hide password toggle beside the field.
        reveal = QToolButton()
        reveal.setCheckable(True)
        reveal.setText('👁')
        reveal.setToolTip(_('Show password'))
        reveal.setCursor(Qt.PointingHandCursor)
        reveal.toggled.connect(
            lambda on: self.password_entry.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password))
        pw_row = QWidget()
        pw_layout = QHBoxLayout(pw_row)
        pw_layout.setContentsMargins(0, 0, 0, 0)
        pw_layout.addWidget(self.password_entry, 1)
        pw_layout.addWidget(reveal)

        self.explicit_filter_check = QCheckBox(_('Explicit Content Filter'))
        self.explicit_filter_check.setEnabled(False)
        self.explicit_filter_check.setTristate(True)

        form = QFormLayout()
        form.addRow(_('Email:'), self.email_entry)
        form.addRow(_('Password:'), pw_row)
        form.addRow('', self.explicit_filter_check)

        self.email_entry.textChanged.connect(self._update_apply_sensitivity)
        self.password_entry.textChanged.connect(self._update_apply_sensitivity)
        return self._page(form)

    # -- audio page --------------------------------------------------------
    def _build_audio_page(self):
        self.quality_combo = QComboBox()
        for label, value in _QUALITY_LABELS:
            self.quality_combo.addItem(label, value)

        form = QFormLayout()
        form.addRow(_('Streaming quality:'), self.quality_combo)
        hint = QLabel(_('The 10-band equalizer and ReplayGain volume '
                        'normalization are in the Plugins section.'))
        hint.setWordWrap(True)
        hint.setStyleSheet('color: palette(mid);')
        form.addRow('', hint)
        return self._page(form)

    # -- network page ------------------------------------------------------
    def _build_network_page(self):
        self.proxy_entry = QLineEdit()
        self.control_proxy_entry = QLineEdit()
        self.control_proxy_pac_entry = QLineEdit()
        if not pacparser:
            self.control_proxy_pac_entry.setEnabled(False)
            self.control_proxy_pac_entry.setToolTip(_('Please install python-pacparser'))

        form = QFormLayout()
        form.addRow(_('Proxy:'), self.proxy_entry)
        form.addRow(_('Control proxy:'), self.control_proxy_entry)
        form.addRow(_('Control proxy PAC:'), self.control_proxy_pac_entry)
        hint = QLabel(_('Proxies are only used for the Pandora connection.'))
        hint.setWordWrap(True)
        hint.setStyleSheet('color: palette(mid);')
        form.addRow('', hint)
        return self._page(form)

    # -- plugins page ------------------------------------------------------
    def _build_plugins_page(self):
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.addStretch(1)  # keeps rows pinned to the top

        self._plugins_container = container
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        scroll.setFrameShape(QFrame.NoFrame)
        return scroll

    # -- about page --------------------------------------------------------
    def _build_about_page(self):
        title = QLabel('<h2>Pyrrha</h2>')
        version = QLabel(_('Version {}').format(__version__))
        version.setStyleSheet('color: palette(mid);')
        blurb = QLabel(_('A skinnable Qt audio player with classic Winamp 2.x '
                         'fidelity — Pandora radio and local files, built on '
                         "Pithos' core."))
        blurb.setWordWrap(True)
        links = QLabel(
            '<a href="https://github.com/k5blazerfl/Pyrrha">Pyrrha</a> · '
            '<a href="https://pithos.github.io">Pithos</a> · GPL-3.0')
        links.setOpenExternalLinks(True)

        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(title)
        v.addWidget(version)
        v.addSpacing(8)
        v.addWidget(blurb)
        v.addSpacing(8)
        v.addWidget(links)
        v.addStretch(1)
        return page

    @staticmethod
    def _page(inner_layout):
        """Wrap a page layout so its content sits at the top-left, not stretched."""
        page = QWidget()
        v = QVBoxLayout(page)
        v.addLayout(inner_layout)
        v.addStretch(1)
        return page

    def set_plugins(self, plugins):
        """Populate the Plugins page. Called by the loader once plugins exist."""
        layout = self._plugins_container.layout()
        # Clear any existing rows (keep the trailing stretch).
        for row in self._plugin_rows:
            row.setParent(None)
        self._plugin_rows = []

        for name in sorted(plugins, key=_friendly_plugin_name):
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
        self.ok_btn.setEnabled(ok)
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
    def _set_if_changed(self, key, value):
        # Every write emits ``changed`` (which the window acts on — a proxy write
        # forces a Pandora reconnect), so only write when the value actually
        # differs. Otherwise applying one setting spuriously reconnects.
        if self._settings[key] != value:
            self._settings[key] = value

    def _write_plain_settings(self):
        self._set_if_changed('proxy', self.proxy_entry.text())
        self._set_if_changed('control-proxy', self.control_proxy_entry.text())
        self._set_if_changed('control-proxy-pac', self.control_proxy_pac_entry.text())
        self._set_if_changed('audio-quality', self.quality_combo.currentData())

    def _apply(self, close_after):
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
            if close_after:
                self.hide()

        if self._last_email != email or self._last_password != password:
            SecretService.set_account_password(self._last_email, email, password, stored)
        else:
            self.applied.emit()
            if close_after:
                self.hide()
