// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include <QString>
#include <QUrl>

namespace pyrrha {

// One playable item, whatever its source (a local file, an internet-radio
// stream, a Pandora track). Sources produce Tracks; the engine plays a Track's
// url. Deliberately a plain value type — no Qt object identity, cheap to copy.
struct Track {
    QUrl url;
    QString title;
    QString artist;
    QString album;
    qint64 durationMs = 0;      // 0 when unknown (e.g. a live stream)
    QString sourceId;           // "local", "radio", "pandora", …

    // "Artist — Title", or just the title, or the file name as a last resort.
    QString displayTitle() const {
        if (!title.isEmpty() && !artist.isEmpty())
            return artist + QStringLiteral(" — ") + title;
        if (!title.isEmpty())
            return title;
        const QString name = url.fileName();
        return name.isEmpty() ? url.toString() : name;
    }
};

}  // namespace pyrrha
