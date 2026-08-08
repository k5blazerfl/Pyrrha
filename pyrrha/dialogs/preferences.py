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

# How many songs to keep queued ahead of the current one (see prequeue-size).
_PREQUEUE_LABELS = [
    (_('Off'), 0),
    (_('4 songs'), 4),
    (_('8 songs'), 8),
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
        self._window = parent          # PyrrhaWindow, for skin-mode get/set
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
        self._add_page(_('Interface'), 'preferences-desktop-theme', self._build_interface_page())
        self._add_page(_('Audio'), 'audio-card', self._build_audio_page())
        self._add_page(_('Network'), 'preferences-system-network', self._build_network_page())
        self._add_page(_('Visualizer'), 'multimedia-volume-control', self._build_visualizer_page())
        self._add_page(_('Shortcuts'), 'preferences-desktop-keyboard', self._build_shortcuts_page())
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

        self.prequeue_combo = QComboBox()
        for label, value in _PREQUEUE_LABELS:
            self.prequeue_combo.addItem(label, value)

        form = QFormLayout()
        form.addRow(_('Streaming quality:'), self.quality_combo)
        form.addRow(_('Pre-queue songs:'), self.prequeue_combo)
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

    # -- interface page ----------------------------------------------------
    def _build_interface_page(self):
        self.startup_view_combo = QComboBox()
        self.startup_view_combo.addItem(_('Pithos Classic'), False)
        self.startup_view_combo.addItem(_('Skinned (Winamp)'), True)
        self.skin_mode_combo = QComboBox()
        self.skin_mode_combo.addItem(_('WinAMP 2.x (Classic)'), 'classic')
        self.skin_mode_combo.addItem(_('Pyrrha (Modern)'), 'modern')
        self.sort_stations_check = QCheckBox(_('Sort stations alphabetically'))
        self.scrobble_radio_check = QCheckBox(_('Scrobble internet radio to Last.fm'))

        form = QFormLayout()
        form.addRow(_('Start in:'), self.startup_view_combo)
        form.addRow(_('Skinned mode:'), self.skin_mode_combo)
        form.addRow('', self.sort_stations_check)
        form.addRow('', self.scrobble_radio_check)
        return self._page(form)

    # -- visualizer page ---------------------------------------------------
    def _build_visualizer_page(self):
        from ..skinned import viswindow as vis
        self.vis_mode_combo = QComboBox()
        for m in range(6):
            self.vis_mode_combo.addItem(_(vis._MODE_NAMES[m]), m)
        self.vis_preset_combo = QComboBox()
        for p in range(4):
            self.vis_preset_combo.addItem(_(vis._PRESET_NAMES[p]), p)
        self.vis_sens_combo = QComboBox()
        for label, g in vis._SENSITIVITY:
            self.vis_sens_combo.addItem(_(label), g)
        self.vis_falloff_combo = QComboBox()
        for label, f in vis._FALLOFF:
            self.vis_falloff_combo.addItem(_(label), f)
        self.vis_peak_check = QCheckBox(_('Peak hold'))
        self.vis_open_btn = QPushButton(_('Open Visualizer Window'))
        self.vis_open_btn.clicked.connect(self._open_visualizer)

        form = QFormLayout()
        form.addRow(_('Default mode:'), self.vis_mode_combo)
        form.addRow(_('Color preset:'), self.vis_preset_combo)
        form.addRow(_('Sensitivity:'), self.vis_sens_combo)
        form.addRow(_('Falloff:'), self.vis_falloff_combo)
        form.addRow('', self.vis_peak_check)
        form.addRow('', self.vis_open_btn)
        hint = QLabel(_('These also apply live to an open visualizer window.'))
        hint.setWordWrap(True)
        hint.setStyleSheet('color: palette(mid);')
        form.addRow('', hint)
        return self._page(form)

    def _open_visualizer(self):
        """Open the large visualizer window from the Preferences button. Persist
        the current visualizer settings first (without touching credentials) so
        the window reflects the chosen mode/preset."""
        self._write_plain_settings()
        if self._window is not None and hasattr(self._window, 'open_visualizer'):
            self._window.open_visualizer()

    # -- shortcuts page (read-only reference) ------------------------------
    def _build_shortcuts_page(self):
        rows = [
            (_('Play / Pause / Stop'), 'X / C / V'),
            (_('Previous / Next'), 'Z / B'),
            (_('Open files'), 'L'),
            (_('Jump to File'), 'J'),
            (_('Jump to Time'), 'Ctrl+J'),
            (_('File Info / Edit Tags'), 'Alt+3'),
            (_('Volume up / down'), '↑ / ↓'),
            (_('Seek back / forward'), '← / →'),
            (_('Shuffle / Repeat'), 'S / R'),
            (_('Double size'), 'Ctrl+D'),
            (_('Always on top'), 'Ctrl+A'),
            (_('Preferences'), 'Ctrl+P'),
            (_('Skin browser'), 'Alt+S'),
            (_('Playlist nav / play / remove'), '↑↓ PgUp/Dn · Enter · Del'),
            (_('Visualizer modes'), '1–6'),
            (_('Visualizer fullscreen / peak-hold'), 'F / P'),
        ]
        form = QFormLayout()
        for action, keys in rows:
            key_label = QLabel(keys)
            key_label.setStyleSheet('font-family: monospace;')
            form.addRow(action + ':', key_label)
        note = QLabel(_('Keyboard shortcuts work in the skinned (Winamp) view.'))
        note.setWordWrap(True)
        note.setStyleSheet('color: palette(mid);')
        form.addRow('', note)

        inner = QWidget()
        inner.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFrameShape(QFrame.NoFrame)
        return scroll

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

        self._select_data(self.quality_combo, self._settings['audio-quality'])
        self._select_data(self.prequeue_combo, self._settings['prequeue-size'])

        # Interface
        self._select_data(self.startup_view_combo, self._settings['skinned-view'])
        if self._window is not None and hasattr(self._window, 'get_skin_mode'):
            self._select_data(self.skin_mode_combo, self._window.get_skin_mode())
        self.sort_stations_check.setChecked(self._settings['sort-stations'])
        self.scrobble_radio_check.setChecked(self._settings['scrobble-radio'])

        # Visualizer
        self._select_data(self.vis_mode_combo, self._settings['vis-mode'])
        self._select_data(self.vis_preset_combo, self._settings['vis-preset'])
        self._select_closest(self.vis_sens_combo, self._settings['vis-gain'])
        self._select_closest(self.vis_falloff_combo, self._settings['vis-falloff'])
        self.vis_peak_check.setChecked(self._settings['vis-peak-hold'])

        def got_password(password):
            self._last_password = password
            self.password_entry.setText(password)
            self._update_apply_sensitivity()

        SecretService.get_account_password(self._last_email, got_password)
        self._update_apply_sensitivity()

    @staticmethod
    def _select_data(combo, value):
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    @staticmethod
    def _select_closest(combo, value):
        """Select the combo item whose data is numerically nearest ``value``
        (sensitivity/falloff can hold a non-preset float set via hotkeys)."""
        best, best_d = 0, None
        for i in range(combo.count()):
            d = abs(float(combo.itemData(i)) - float(value))
            if best_d is None or d < best_d:
                best, best_d = i, d
        combo.setCurrentIndex(best)

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
        self._set_if_changed('prequeue-size', self.prequeue_combo.currentData())
        # Interface
        self._set_if_changed('skinned-view', self.startup_view_combo.currentData())
        self._set_if_changed('sort-stations', self.sort_stations_check.isChecked())
        self._set_if_changed('scrobble-radio', self.scrobble_radio_check.isChecked())
        # Visualizer (a live window picks these up via settings.changed)
        self._set_if_changed('vis-mode', self.vis_mode_combo.currentData())
        self._set_if_changed('vis-preset', self.vis_preset_combo.currentData())
        self._set_if_changed('vis-gain', self.vis_sens_combo.currentData())
        self._set_if_changed('vis-falloff', self.vis_falloff_combo.currentData())
        self._set_if_changed('vis-peak-hold', self.vis_peak_check.isChecked())
        # Skin mode lives in a file (get/set_skin_mode), not settings.
        if self._window is not None and hasattr(self._window, 'set_skin_mode'):
            mode = self.skin_mode_combo.currentData()
            if self._window.get_skin_mode() != mode:
                self._window.set_skin_mode(mode)

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
