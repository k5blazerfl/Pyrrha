# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""One-time migration of an existing Pithos configuration into Pyrrha.

Copies every GSettings key (including the plugin child schemas) from
``io.github.Pithos`` into Pyrrha's own schema, and the stored Pandora password
from the ``io.github.Pithos.Account`` libsecret entry to Pyrrha's. It is
**non-destructive** — Pithos' own data is left untouched, so both apps keep
working — and idempotent: it runs only while Pyrrha has no email configured yet
and Pithos does.
"""

import logging

import gi
gi.require_version('Secret', '1')
from gi.repository import Gio, GLib, Secret

from . import SETTINGS_SCHEMA

PITHOS_SCHEMA = 'io.github.Pithos'
PITHOS_ACCOUNT = 'io.github.Pithos.Account'
PYRRHA_ACCOUNT = SETTINGS_SCHEMA + '.Account'


def _schema_installed(schema_id):
    source = Gio.SettingsSchemaSource.get_default()
    return source is not None and source.lookup(schema_id, True) is not None


def _copy_keys(src, dst):
    for key in src.props.settings_schema.list_keys():
        dst.set_value(key, src.get_value(key))


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
    if not _schema_installed(SETTINGS_SCHEMA) or not _schema_installed(PITHOS_SCHEMA):
        return

    dst = Gio.Settings.new(SETTINGS_SCHEMA)
    src = Gio.Settings.new(PITHOS_SCHEMA)

    # Trigger only for a still-unconfigured Pyrrha with something to migrate.
    if dst['email'] or not src['email']:
        return

    logging.info('Migrating configuration from Pithos ({} -> {})'.format(
        PITHOS_SCHEMA, SETTINGS_SCHEMA))
    _copy_keys(src, dst)

    for name in src.props.settings_schema.list_children():
        try:
            _copy_keys(src.get_child(name), dst.get_child(name))
        except GLib.Error as e:
            logging.warning('Skipped migrating plugin "{}": {}'.format(name, e))

    _migrate_password(src['email'])
    logging.info('Migration from Pithos complete')
