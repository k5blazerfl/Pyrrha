# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Configuration storage for Pyrrha, backed by :class:`QSettings`.

This replaces the ``Gio.Settings`` (GSettings) layer Pyrrha inherited from
Pithos. The public surface deliberately mirrors the small slice of the GSettings
API the rest of the app relied on, so call sites barely change:

* ``settings['key']`` reads and ``settings['key'] = value`` writes, with types
  and defaults taken from the tables below (they used to live in the
  ``.gschema.xml``).
* :meth:`Settings.set_string` / :meth:`~Settings.set_double` typed writers.
* :meth:`Settings.get_child` for the per-plugin child "schemas".
* a ``changed`` Qt signal that fires on every write, standing in for GSettings'
  ``changed::key`` notifications.

The one behavioural difference from GSettings is notification scope. GSettings
broadcasts a change to *every* ``Gio.Settings`` instance of a schema (even across
processes); QSettings does not. We recover the in-process half of that by making
the root node a process-wide singleton (see :func:`get_settings`), so the window,
the preferences dialog and the stations popover all observe the same object.
Cross-process live updates are dropped — Pyrrha is the only writer of its config.
"""

from PySide6.QtCore import QObject, QSettings, Signal

from . import APP_ID

# Root-schema keys: name -> (default, python type). Mirrors the old
# io.github.k5blazerfl.Pyrrha schema. The dead ``win-pos`` (ii) key, never read
# or written in code, is intentionally dropped.
_ROOT_DEFAULTS = {
    'email': ('', str),
    'pandora-one': (False, bool),
    'sort-stations': (False, bool),
    'last-station-id': ('', str),
    'proxy': ('', str),
    'control-proxy': ('', str),
    'control-proxy-pac': ('', str),
    'force-client': ('', str),
    'volume': (0.7, float),
    'balance': (0.0, float),
    'audio-quality': ('highQuality', str),
    # How many unskipped Pandora songs to keep pre-queued ahead of the current
    # one (0 = off; only the next batch is fetched as the queue runs out).
    'prequeue-size': (8, int),
    # Which top-level view the player was last in: True = skinned (Winamp)
    # view, False = standard (native) window. Restored at startup.
    'skinned-view': (False, bool),
    # Local-playback play order (only affects local files).
    'shuffle': (False, bool),
    'repeat': (False, bool),
    # Visualizer window defaults (remembered across sessions).
    'vis-mode': (0, int),          # VIS_BARS
    'vis-preset': (0, int),        # PRESET_SKIN
    'vis-gain': (1.0, float),      # input sensitivity
    'vis-falloff': (0.05, float),  # bar decay per frame
    'vis-peak-hold': (False, bool),
    # EQ "AUTO" button: auto-select a genre preset from the current
    # station/song metadata as tracks change. Opt-in (off preserves the
    # manual + per-station-memory behavior).
    'eq-auto': (False, bool),
}

# Plugin child schema. Two flavours, matching the old .plugin / .plugin-enabled
# children — the only difference is the default of ``enabled``.
_PLUGIN_DEFAULTS = {'enabled': (False, bool), 'data': ('', str)}
_PLUGIN_ENABLED_DEFAULTS = {'enabled': (True, bool), 'data': ('', str)}

# Plugins whose ``enabled`` key defaults to true (were ``.plugin-enabled``
# children in the schema). Everything else defaults to disabled.
DEFAULT_ENABLED = frozenset({
    'mediakeys', 'screensaver-pause', 'mpris', 'journald-logging',
})


def _coerce(val, typ, default):
    """Coerce a QSettings value to ``typ``. The INI backend can hand back
    strings for bools/numbers, so never trust the stored Python type."""
    if val is None:
        return default
    if typ is bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ('1', 'true', 'yes', 'on')
        return bool(val)
    if typ is float:
        try:
            return float(val)
        except (TypeError, ValueError):
            return default
    if typ is int:
        try:
            return int(val)
        except (TypeError, ValueError):
            return default
    return val if isinstance(val, str) else str(val)


class Settings(QObject):
    """A node in Pyrrha's settings tree.

    The root node owns the underlying :class:`QSettings`; children share that
    same backend and only differ by a key prefix, so a single ``.conf`` file
    holds everything (root keys at top level, plugin keys under a group).
    """

    # Emits the (node-relative) key name whenever a value is written through
    # this node. Replaces GSettings' ``changed::key`` detail signal — connect a
    # slot and filter on the key.
    changed = Signal(str)

    def __init__(self, backend=None, prefix='', defaults=None, parent=None):
        super().__init__(parent)
        self._q = backend or QSettings(
            QSettings.IniFormat, QSettings.UserScope, APP_ID, 'Pyrrha')
        self._prefix = prefix
        self._defaults = _ROOT_DEFAULTS if defaults is None else defaults

    def _full(self, key):
        return '{}/{}'.format(self._prefix, key) if self._prefix else key

    def __getitem__(self, key):
        default, typ = self._defaults.get(key, ('', str))
        return _coerce(self._q.value(self._full(key), default), typ, default)

    def __setitem__(self, key, value):
        self._q.setValue(self._full(key), value)
        # Flush immediately so a change survives a non-graceful exit (kill,
        # crash, logout) — QSettings otherwise only writes on sync()/destruction,
        # and aboutToQuit does not fire on SIGTERM. Syncing a small INI is cheap.
        self._q.sync()
        self.changed.emit(key)

    # Typed writers kept for call-site compatibility with Gio.Settings.
    def set_string(self, key, value):
        self[key] = str(value)

    def set_double(self, key, value):
        self[key] = float(value)

    def set_int(self, key, value):
        self[key] = int(value)

    def get_child(self, name):
        """Return the child node for a plugin, sharing this node's backend.

        The default for ``enabled`` follows :data:`DEFAULT_ENABLED`, reproducing
        the old .plugin / .plugin-enabled split without a schema.
        """
        defaults = (_PLUGIN_ENABLED_DEFAULTS if name in DEFAULT_ENABLED
                    else _PLUGIN_DEFAULTS)
        return Settings(backend=self._q, prefix=self._full(name),
                        defaults=defaults, parent=self)

    def sync(self):
        self._q.sync()


_root = None


def get_settings():
    """Return the process-wide root settings node, creating it on first use."""
    global _root
    if _root is None:
        _root = Settings()
    return _root
