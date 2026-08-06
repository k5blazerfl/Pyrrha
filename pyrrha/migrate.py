# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""One-time migration of an existing Pithos configuration into Pyrrha.

Copies the config keys (including the plugin child schemas) from Pithos'
``io.github.Pithos`` GSettings schema into Pyrrha's :mod:`~pyrrha.settings`
(QSettings) store, and the stored Pandora password from the
``io.github.Pithos.Account`` libsecret entry to Pyrrha's. It is
**non-destructive** — Pithos' own data is left untouched, so both apps keep
working — and idempotent: it runs only while Pyrrha has no email configured yet
and Pithos does.

Pithos' config still lives in GSettings/dconf regardless of what Pyrrha uses, so
this module keeps a read-only ``Gio`` dependency purely to read the legacy
source; nothing here writes GSettings.
"""

import logging

import gi
gi.require_version('Secret', '1')
from gi.repository import Gio, GLib, Secret

from . import SETTINGS_SCHEMA
from .settings import get_settings, _ROOT_DEFAULTS

PITHOS_SCHEMA = 'io.github.Pithos'
PITHOS_ACCOUNT = 'io.github.Pithos.Account'
PYRRHA_ACCOUNT = SETTINGS_SCHEMA + '.Account'

# Plugin child keys carried across (matches pyrrha.settings plugin schemas).
_PLUGIN_KEYS = ('enabled', 'data')


def _schema_installed(schema_id):
    source = Gio.SettingsSchemaSource.get_default()
    return source is not None and source.lookup(schema_id, True) is not None


def _copy_keys(src, dst, keys):
    """Copy ``keys`` present in the ``src`` Gio.Settings into ``dst`` (a
    :class:`pyrrha.settings.Settings` node)."""
    available = src.props.settings_schema.list_keys()
    for key in keys:
        if key in available:
            dst[key] = src[key]


def _migrate_password(email):
    old_schema = Secret.Schema.new(
        PITHOS_ACCOUNT, Secret.SchemaFlags.NONE,
        {'email': Secret.SchemaAttributeType.STRING})
    new_schema = Secret.Schema.new(
        PYRRHA_ACCOUNT, Secret.SchemaFlags.NONE,
        {'email': Secret.SchemaAttributeType.STRING})
    try:
        password = Secret.password_lookup_sync(old_schema, {'email': email}, None)
    except GLib.Error as e:
        logging.warning('Could not read Pithos password for migration: {}'.format(e))
        return
    if not password:
        return
    try:
        Secret.password_store_sync(
            new_schema, {'email': email}, Secret.COLLECTION_DEFAULT,
            'Pandora Account', password, None)
        logging.info('Migrated stored Pandora password from Pithos')
    except GLib.Error as e:
        logging.warning('Could not store migrated password: {}'.format(e))


def maybe_migrate_from_pithos():
    """Copy Pithos config + credentials into Pyrrha, once, if applicable."""
    if not _schema_installed(PITHOS_SCHEMA):
        return

    dst = get_settings()
    src = Gio.Settings.new(PITHOS_SCHEMA)

    # Trigger only for a still-unconfigured Pyrrha with something to migrate.
    if dst['email'] or not src['email']:
        return

    logging.info('Migrating configuration from Pithos ({} -> QSettings)'.format(
        PITHOS_SCHEMA))
    _copy_keys(src, dst, _ROOT_DEFAULTS.keys())

    for name in src.props.settings_schema.list_children():
        try:
            _copy_keys(src.get_child(name), dst.get_child(name), _PLUGIN_KEYS)
        except GLib.Error as e:
            logging.warning('Skipped migrating plugin "{}": {}'.format(name, e))

    dst.sync()
    _migrate_password(src['email'])
    logging.info('Migration from Pithos complete')
