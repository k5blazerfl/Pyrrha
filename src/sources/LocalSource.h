// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include "sources/SourceProvider.h"

namespace pyrrha {

// The built-in local-file source. Tracks are added explicitly (open files) or by
// scanning a folder for known audio extensions. Metadata is minimal for now —
// the title is derived from the file name; tags and duration are filled in later
// (the engine reports duration once a track is loaded). No recursive-scan depth
// limit yet; that's fine for the prototype.
class LocalSource : public SourceProvider {
public:
    QString id() const override { return QStringLiteral("local"); }
    QString name() const override { return QStringLiteral("Local Files"); }
    QVector<Track> tracks() const override { return m_tracks; }

    // Add individual files (non-audio paths are ignored). Returns how many were
    // added.
    int addFiles(const QStringList &paths);

    // Recursively scan a directory for audio files. Returns how many were added.
    int addFolder(const QString &dir);

    void clear() { m_tracks.clear(); }

    // Replace a track (used by the metadata scanner to fill in real tags).
    void updateTrack(int index, const Track &track) {
        if (index >= 0 && index < m_tracks.size())
            m_tracks[index] = track;
    }

    // The audio file extensions we accept (lower-case, no dot).
    static const QStringList &audioExtensions();

private:
    Track makeTrack(const QString &path) const;

    QVector<Track> m_tracks;
};

}  // namespace pyrrha
