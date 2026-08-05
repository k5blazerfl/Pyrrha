# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Adapted from Pithos' plugin.py (C) 2010 Kevin Mehall.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Minimal plugin base for Pyrrha.

Same lifecycle as Pithos' ``PithosPlugin`` (prepare → enable → disable) but a
plain Python object rather than a ``GObject.Object`` — plugins connect to the
window's Qt signals instead of GObject signals. ``settings`` is a
``Gio.Settings`` child assigned by the loader.
"""

import logging


class PyrrhaPlugin:
    _PYRRHA_PLUGIN = True
    preference = None
    description = ''

    def __init__(self, name, window, bus):
        self.name = name
        self.window = window
        self.bus = bus
        self.settings = None
        self.preferences_dialog = None
        self.prepared = False
        self._enabled = False
        self.error = None

    @property
    def enabled(self):
        return self._enabled

    def enable(self):
        if not self.prepared:
            logging.info('Preparing plugin {}'.format(self.name))
            self.on_prepare()
        elif not self.error and not self._enabled:
            self._enable()

    def _enable(self):
        logging.info('Enabling plugin {}'.format(self.name))
        self.on_enable()
        self._enabled = True

    def disable(self):
        if self._enabled:
            logging.info('Disabling plugin {}'.format(self.name))
            self.on_disable()
            self._enabled = False

    def prepare_complete(self, error=None):
        self.prepared = True
        if error:
            self.on_error(error)
        else:
            self._enable()

    def on_error(self, error):
        self.error = error
        logging.info('Plugin {} disabled: {}'.format(self.name, error))
        if self.settings is not None:
            self.settings['enabled'] = False

    def on_prepare(self):
        pass

    def on_enable(self):
        pass

    def on_disable(self):
        pass


class ErrorPlugin(PyrrhaPlugin):
    def __init__(self, name, error):
        logging.error('Error loading plugin {}: {}'.format(name, error))
        self.name = name
        self.window = None
        self.bus = None
        self.settings = None
        self.preferences_dialog = None
        self.prepared = True
        self.error = error
        self._enabled = False
