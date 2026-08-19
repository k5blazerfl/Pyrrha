// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include <QObject>
#include <QVector>

#include "engine/PlayerEngine.h"
#include "model/Track.h"

namespace pyrrha {

// The playback controller: owns the play queue and drives a PlayerEngine. The UI
// talks to this, never to the engine directly. Source-agnostic — the queue is
// just Tracks, wherever they came from.
class Player : public QObject {
    Q_OBJECT
public:
    // Does not take ownership of engine; the caller keeps it alive (it is
    // parented elsewhere / on the stack for the app's lifetime).
    explicit Player(PlayerEngine *engine, QObject *parent = nullptr);

    void setQueue(const QVector<Track> &tracks);
    const QVector<Track> &queue() const { return m_queue; }

    // Replace one queue entry in place (e.g. when its tags arrive). If it's the
    // current track, currentChanged is re-emitted so the UI refreshes.
    void updateTrack(int index, const Track &track);

    void playIndex(int index);       // load + play the queue item at index
    void togglePlayPause();
    void next();
    void previous();
    void stop();
    void seek(qint64 ms);
    void setVolume(qreal volume);    // 0.0 … 1.0

    int currentIndex() const { return m_index; }
    const Track *current() const;    // nullptr when nothing is loaded
    qreal volume() const { return m_volume; }
    PlayerEngine *engine() const { return m_engine; }

signals:
    void currentChanged(int index);  // -1 when the queue emptied / stopped
    void queueChanged();
    void seeked(qint64 ms);          // a discontinuous position change (a seek)
    void volumeChanged(qreal volume);

private:
    void loadAndPlay(int index);

    PlayerEngine *m_engine;
    QVector<Track> m_queue;
    int m_index = -1;
    qreal m_volume = 0.8;
};

}  // namespace pyrrha
