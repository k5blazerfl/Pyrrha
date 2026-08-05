# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Ported from Pithos' plugins/auto_volume_normalization.py (C) 2017 Jason Gray.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""ReplayGain-based apparent-volume normalization.

Turns on the ``rglimiter`` element and feeds each song's ``trackGain`` to
``rgvolume`` as its ``fallback-gain`` so tracks play at a consistent perceived
loudness. Both elements are already present in Pyrrha's GStreamer pipeline (see
``PyrrhaWindow.init_core``). On disable it resets them and warns, since removing
normalization can cause a sudden jump in volume.
"""

from PySide6.QtWidgets import QMessageBox

from ..plugin import PyrrhaPlugin


class AutoVolumeNormalization(PyrrhaPlugin):
    preference = 'enable_autovolume'
    description = 'Normalize apparent volume'

    def on_prepare(self):
        self._conn = None
        self.prepare_complete()

    def on_enable(self):
        self._conn = self._on_song_changed
        self.window.song_changed.connect(self._conn)
        self.window.rglimiter.set_property('enabled', True)
        if self.window.current_song is not None:
            self._on_song_changed(self.window.current_song)

    def on_disable(self):
        if self._conn is not None:
            try:
                self.window.song_changed.disconnect(self._conn)
            except (RuntimeError, TypeError):
                pass
            self._conn = None
        self._reset_and_warn()

    def _on_song_changed(self, song=None):
        song = song or self.window.current_song
        if song is not None:
            self.window.rgvolume.set_property('fallback-gain', song.trackGain)

    def _reset_and_warn(self):
        if self.window.playing:
            self.window.pause()
            text = _('Pyrrha Has Been Paused')
        else:
            text = _('Pyrrha Is Paused')

        self.window.rgvolume.set_property('fallback-gain', 0.0)
        self.window.rglimiter.set_property('enabled', False)

        # Non-blocking so nothing freezes.
        box = QMessageBox(QMessageBox.Warning, text,
                          _('Please lower the volume before resuming playback, as you '
                            'may notice a sudden volume increase now that normalization '
                            'is disabled.'),
                          QMessageBox.Ok, self.window)
        box.setModal(False)
        box.finished.connect(box.deleteLater)
        box.show()
