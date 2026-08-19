// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include "engine/PlayerEngine.h"

class QMediaPlayer;
class QAudioOutput;

namespace pyrrha {

// The default PlayerEngine, backed by Qt6::Multimedia (QMediaPlayer +
// QAudioOutput). Basic playback only for now — gapless, ReplayGain and a graphic
// EQ are the reasons a GStreamer engine may join it later behind PlayerEngine.
class QtMultimediaEngine : public PlayerEngine {
    Q_OBJECT
public:
    explicit QtMultimediaEngine(QObject *parent = nullptr);
    ~QtMultimediaEngine() override;

    void load(const QUrl &url) override;
    void play() override;
    void pause() override;
    void stop() override;
    void seek(qint64 ms) override;
    void setVolume(qreal volume) override;

    State state() const override { return m_state; }
    qint64 position() const override;
    qint64 duration() const override;

private:
    QMediaPlayer *m_player;
    QAudioOutput *m_output;
    State m_state = State::Stopped;
};

}  // namespace pyrrha
