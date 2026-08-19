// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include <QObject>
#include <QUrl>

namespace pyrrha {

// The audio backend, abstracted so the rest of the app never touches Qt
// Multimedia (or, later, GStreamer) directly. QtMultimediaEngine is the default
// implementation; a GStreamerEngine could be dropped in for gapless / ReplayGain
// / EQ without any change above this interface.
class PlayerEngine : public QObject {
    Q_OBJECT
public:
    enum class State { Stopped, Playing, Paused };
    Q_ENUM(State)

    using QObject::QObject;
    ~PlayerEngine() override = default;

    virtual void load(const QUrl &url) = 0;   // load without starting playback
    virtual void play() = 0;
    virtual void pause() = 0;
    virtual void stop() = 0;
    virtual void seek(qint64 ms) = 0;
    virtual void setVolume(qreal volume) = 0;  // 0.0 … 1.0

    virtual State state() const = 0;
    virtual qint64 position() const = 0;       // ms
    virtual qint64 duration() const = 0;       // ms (0 when unknown)

signals:
    void stateChanged(pyrrha::PlayerEngine::State state);
    void positionChanged(qint64 ms);
    void durationChanged(qint64 ms);
    void trackEnded();                          // media reached its natural end
    void error(const QString &message);
};

}  // namespace pyrrha
