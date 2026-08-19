// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include <QObject>
#include <QQueue>

#include "model/Track.h"

class QMediaPlayer;
class QMediaMetaData;
class QTimer;

namespace pyrrha {

// Reads real tags (title / artist / album / duration) for local files using
// QMediaMetaData. QMediaPlayer populates metadata asynchronously once a source
// has loaded, so this owns a dedicated player and walks a queue one file at a
// time — never playing audio, just loading each to read its metadata — emitting
// an enriched Track per item as it goes. Cheap enough for a prototype library;
// it can be swapped for a threaded taglib scan later without touching callers.
class MetadataScanner : public QObject {
    Q_OBJECT
public:
    explicit MetadataScanner(QObject *parent = nullptr);
    ~MetadataScanner() override;

    // Enqueue tracks for probing. ``baseIndex`` is the absolute index of the
    // first track (so updates map back onto the caller's list). Safe to call
    // again while a scan is running — the new items are appended.
    void scan(const QVector<Track> &tracks, int baseIndex = 0);

    // Fill a Track's empty fields from metadata (exposed for reuse/testing).
    static void applyMetaData(Track &track, const QMediaMetaData &md,
                              qint64 durationMs);

signals:
    void trackUpdated(int index, const pyrrha::Track &track);
    void finished();

private:
    void probeNext();
    void tryFinalize();                  // finalize once loaded + tags are in
    void finishCurrent(bool readMeta);   // emit (if loaded), then advance

    struct Pending {
        int index;
        Track track;
    };

    QMediaPlayer *m_player;
    QTimer *m_settle;          // grace period for late string tags after load
    QQueue<Pending> m_pending;
    bool m_busy = false;       // a scan loop is running
    bool m_awaiting = false;   // waiting on the current item's load
};

}  // namespace pyrrha
