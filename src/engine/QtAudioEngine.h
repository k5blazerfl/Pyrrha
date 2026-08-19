// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include <QAudioFormat>
#include <QByteArray>

#include "engine/PlayerEngine.h"

class QAudioDecoder;
class QAudioSink;
class QBuffer;
class QTimer;

namespace pyrrha {

// The native low-level engine: QAudioDecoder decodes a file to raw PCM that *we*
// own, and QAudioSink plays it. Unlike QMediaPlayer this exposes the samples, so
// it is the foundation the killer-app features grow on — a graphic EQ, ReplayGain
// and gapless become our own DSP in the decode→sink path, with no GStreamer and
// no GLib.
//
// v1 is deliberately simple: decode the whole file into a buffer, then play it
// through a seekable QBuffer. That gives accurate seeking for free and a place to
// hang DSP; streaming decode (play while decoding) and decode-ahead gapless are
// later refinements behind this same interface.
class QtAudioEngine : public PlayerEngine {
    Q_OBJECT
public:
    explicit QtAudioEngine(QObject *parent = nullptr);
    ~QtAudioEngine() override;

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
    void onBufferReady();
    void onDecodeFinished();
    void startSink();
    void teardownSink();
    void setState(State state);

    QAudioDecoder *m_decoder;
    QAudioSink *m_sink = nullptr;
    QBuffer *m_pcmDevice = nullptr;   // seekable view over m_pcm the sink pulls from
    QByteArray m_pcm;                 // the whole decoded track, PCM
    QAudioFormat m_format;            // the device's preferred format (decode target)
    QTimer *m_posTimer;              // drives positionChanged while playing

    State m_state = State::Stopped;
    bool m_ready = false;             // decoding finished — safe to start the sink
    bool m_playRequested = false;     // play() arrived before decoding finished
    qreal m_volume = 0.8;
};

}  // namespace pyrrha
