// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include <QString>
#include <QVector>

#include "model/Track.h"

namespace pyrrha {

// Where music comes from. Local files ship in the core; internet radio and
// Pandora (a separate GPLv3 plugin) implement the same interface, so the player
// and UI treat every source identically — a source is just something that yields
// Tracks. Kept a plain abstract interface (no QObject) so plugins can implement
// it without dragging in moc.
class SourceProvider {
public:
    virtual ~SourceProvider() = default;

    virtual QString id() const = 0;         // stable key, e.g. "local"
    virtual QString name() const = 0;       // human label, e.g. "Local Files"
    virtual QVector<Track> tracks() const = 0;  // the source's current items
};

}  // namespace pyrrha
