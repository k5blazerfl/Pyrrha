// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include <QObject>
#include <QVector>

#include "model/Track.h"

namespace pyrrha {

// Reads real tags (title / artist / album / duration) with TagLib — every common
// format including Ogg/Vorbis/Opus, which Qt's QMediaMetaData can't read on the
// FFmpeg backend. One synchronous call per file, no playback and no media
// pipeline. Kept as a QObject with signals so a threaded scan can drop in later
// behind the same interface without touching callers.
class MetadataScanner : public QObject {
    Q_OBJECT
public:
    explicit MetadataScanner(QObject *parent = nullptr);

    // Read tags for each track, emitting trackUpdated as each is read, then
    // finished(). ``baseIndex`` maps results onto the caller's list.
    void scan(const QVector<Track> &tracks, int baseIndex = 0);

    // Read one local file's tags into a copy of ``track`` (exposed for reuse and
    // testing). Non-local URLs (radio/stream) are returned unchanged.
    static Track readTags(const Track &track);

signals:
    void trackUpdated(int index, const pyrrha::Track &track);
    void finished();
};

}  // namespace pyrrha
