# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Drive the GLib main context from within the Qt event loop.

Pyrrha keeps the GLib-based subsystems that Pithos already relies on
(GStreamer, GSettings, libsecret and the threaded worker that marshals
results back with ``GLib.idle_add``).  All of those deliver their callbacks
through a GLib ``MainContext``.  Since Qt owns the process' event loop and no
GLib main loop is running, nothing would ever dispatch those callbacks.

The bridge below repeatedly iterates the default GLib main context, without
blocking, from a short-interval ``QTimer``.  That single mechanism keeps
GStreamer bus watches, ``GLib.idle_add`` callbacks, ``Gio.Settings`` change
notifications and libsecret's async replies all functioning exactly as they
did under GTK.
"""

from gi.repository import GLib
from PySide6.QtCore import QObject, QTimer


class GLibBridge(QObject):
    # How often (ms) to service the GLib context. 10ms keeps GStreamer bus
    # messages and idle callbacks responsive at a negligible CPU cost.
    INTERVAL_MS = 10
    # Cap the callbacks dispatched per tick so a flood of GLib events can never
    # starve the Qt event loop.
    MAX_ITERATIONS = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self._context = GLib.MainContext.default()
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self._iterate)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _iterate(self):
        count = 0
        # iteration(may_block=False) dispatches at most one pending source and
        # returns immediately when there is nothing to do.
        while self._context.pending() and count < self.MAX_ITERATIONS:
            self._context.iteration(False)
            count += 1
