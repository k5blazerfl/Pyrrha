# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Ported from Pithos' plugins/10_band_equalizer.py (C) 2017 Jason Gray.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""10-band graphic equalizer.

Drives the ``equalizer-10bands`` element that is always present in Pyrrha's
GStreamer pipeline (see ``PyrrhaWindow.init_core``). Enabling the plugin applies
the saved curve; disabling flattens every band to 0 dB (a no-op on the audio).
The per-plugin *Configure…* button in Preferences → Plugins opens the dialog of
sliders — this is the first plugin to use that hook.

Qt's ``QSlider`` is integer-only, so each band uses an int range of -240..120
scaled by 10 to give the -24.0..+12.0 dB range (0.1 dB steps) Pithos used.
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QLabel, QSlider, QVBoxLayout,
)

from ..plugin import PyrrhaPlugin

BANDS = 10
DB_MIN, DB_MAX = -24.0, 12.0
SCALE = 10  # slider int units per dB
BAND_LABELS = ['29 Hz', '59 Hz', '119 Hz', '237 Hz', '474 Hz',
               '947 Hz', '1.9 kHz', '3.8 kHz', '7.5 kHz', '15 kHz']


class EqualizerPlugin(PyrrhaPlugin):
    preference = 'enable_10bandeq'
    description = '-24 to +12 dB'

    def on_prepare(self):
        self.preferences_dialog = EqDialog(self)
        self.prepare_complete()

    def on_enable(self):
        # Apply the saved curve (or persist the current flat one first time).
        data = self.settings['data']
        if not data:
            self.settings['data'] = self.preferences_dialog.get_eq_values()
        else:
            self.preferences_dialog.load_eq_values()

    def on_disable(self):
        # Flatten the audio but keep the saved curve for re-enabling.
        self.preferences_dialog.zero_eq(save=False)


class EqDialog(QDialog):
    def __init__(self, plugin):
        super().__init__(plugin.window)
        self.plugin = plugin
        self.equalizer = plugin.window.equalizer
        self.setWindowTitle(_('10 Band Equalizer'))
        self.setModal(False)

        self._sliders = []
        self._value_labels = []

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        for i in range(BANDS):
            value_lbl = QLabel('0.0')
            value_lbl.setAlignment(Qt.AlignHCenter)

            slider = QSlider(Qt.Vertical)
            slider.setMinimum(int(DB_MIN * SCALE))
            slider.setMaximum(int(DB_MAX * SCALE))
            slider.setValue(0)
            slider.setMinimumHeight(140)
            slider.valueChanged.connect(lambda v, idx=i: self._on_slider_changed(idx, v))

            freq_lbl = QLabel(BAND_LABELS[i])
            freq_lbl.setAlignment(Qt.AlignHCenter)
            freq_lbl.setStyleSheet('color: palette(mid); font-size: small;')

            grid.addWidget(value_lbl, 0, i)
            grid.addWidget(slider, 1, i, Qt.AlignHCenter)
            grid.addWidget(freq_lbl, 2, i)
            self._sliders.append(slider)
            self._value_labels.append(value_lbl)

        buttons = QDialogButtonBox()
        reset = buttons.addButton(_('Reset'), QDialogButtonBox.ResetRole)
        close = buttons.addButton(QDialogButtonBox.Close)
        reset.clicked.connect(lambda: self.zero_eq(save=True))
        close.clicked.connect(self.hide)

        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(buttons)

        # Reflect whatever the element currently has.
        self._sync_sliders_from_element()

    # -- slider <-> element ------------------------------------------------
    def _band_name(self, i):
        return 'band{}'.format(i)

    def _on_slider_changed(self, index, value):
        db = value / SCALE
        self.equalizer.set_property(self._band_name(index), db)
        self._value_labels[index].setText('{:+.1f}'.format(db))
        self.plugin.settings['data'] = self.get_eq_values()

    def _set_band(self, index, db, save):
        """Set a band without triggering the change/save loop."""
        slider = self._sliders[index]
        slider.blockSignals(True)
        slider.setValue(int(round(db * SCALE)))
        slider.blockSignals(False)
        self._value_labels[index].setText('{:+.1f}'.format(db))
        self.equalizer.set_property(self._band_name(index), db)
        if save:
            self.plugin.settings['data'] = self.get_eq_values()

    def _sync_sliders_from_element(self):
        for i in range(BANDS):
            db = float(self.equalizer.get_property(self._band_name(i)))
            slider = self._sliders[i]
            slider.blockSignals(True)
            slider.setValue(int(round(db * SCALE)))
            slider.blockSignals(False)
            self._value_labels[i].setText('{:+.1f}'.format(db))

    # -- API used by the plugin -------------------------------------------
    def get_eq_values(self):
        return ' '.join(str(self.equalizer.get_property(self._band_name(i)))
                        for i in range(BANDS))

    def load_eq_values(self):
        data = self.plugin.settings['data']
        if not data:
            return
        try:
            values = [float(v) for v in data.split(' ')]
        except ValueError:
            logging.warning('Could not parse saved equalizer data')
            return
        for i, v in enumerate(values[:BANDS]):
            self._set_band(i, v, save=False)

    def zero_eq(self, save):
        for i in range(BANDS):
            self._set_band(i, 0.0, save=save)
