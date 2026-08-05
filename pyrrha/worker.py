# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Adapted from Pithos' gobject_worker.py (C) 2010-2012 Kevin Mehall.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Run blocking work off the GUI thread and marshal results back.

Identical in spirit to Pithos' ``GObjectWorker``: a task runs on a daemon
thread and its result (or error) is delivered back on the main thread via
``GLib.idle_add``.  The Qt event loop dispatches those idle callbacks because
:class:`pyrrha.glib_bridge.GLibBridge` keeps the GLib main context serviced.
"""

import logging
import threading
import traceback

from gi.repository import GLib


class Worker:

    def send(self, command, args=(), callback=None, errorback=None):
        def run(data):
            command, args, callback, errorback = data
            try:
                result = command(*args)
                if callback:
                    GLib.idle_add(callback, result)
            except Exception as e:
                e.traceback = traceback.format_exc()
                if errorback:
                    GLib.idle_add(errorback, e)

        if errorback is None:
            errorback = self._default_errorback
        data = command, args, callback, errorback
        thread = threading.Thread(target=run, args=(data,))
        thread.daemon = True
        thread.start()

    def _default_errorback(self, error):
        logging.error("Unhandled exception in worker thread:\n{}".format(error.traceback))
