# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
# Adapted from Pithos' plugin.py (C) 2010 Kevin Mehall.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Load and enable Pyrrha's plugins.

Acquires the session bus asynchronously (via Gio, dispatched through the pumped
GLib context), then instantiates each named plugin, assigns its settings child
(see :mod:`pyrrha.settings`) and enables it if configured. Only a curated set is
loaded for now — the plugin phase currently ships MPRIS and media keys.
"""

import importlib
import logging

from gi.repository import Gio, GLib

from .plugin import ErrorPlugin

# Plugins Pyrrha currently ships, in load order.
PLUGINS = ('mpris', 'mediakeys', 'notify', 'equalizer', 'notification_icon',
           'lastfm', 'inhibit_screensaver', 'journald_logging',
           'auto_volume_normalization', 'screensaver_pause')


def _load_plugin(name, window, bus):
    try:
        module = importlib.import_module('pyrrha.plugins.' + name)
    except ImportError as e:
        return ErrorPlugin(name, str(e))
    for key, item in vars(module).items():
        if getattr(item, '_PYRRHA_PLUGIN', False) and key != 'PyrrhaPlugin':
            return item(name, window, bus)
    return ErrorPlugin(name, 'Could not find plugin class')


def load_plugins(window, plugins=PLUGINS):
    def on_got_bus(source, result, userdata):
        try:
            bus = Gio.bus_get_finish(result)
            logging.info('Got session bus')
        except GLib.Error as e:
            logging.warning('Failed to connect to session bus, some plugins '
                            'will not function: {}'.format(e))
            bus = None

        for name in plugins:
            plugin = window.plugins.get(name) or _load_plugin(name, window, bus)
            window.plugins[name] = plugin

            settings_name = name.replace('_', '-')
            plugin.settings = window.settings.get_child(settings_name)

            if plugin.settings['enabled']:
                plugin.enable()
            else:
                plugin.disable()

        # Populate the preferences dialog's Plugins tab now that they exist.
        window.prefs_dlg.set_plugins(window.plugins)

    Gio.bus_get(Gio.BusType.SESSION, None, on_got_bus, None)
