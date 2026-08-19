// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include <QAudioFormat>

#include "engine/PlayerEngine.h"

class QAudioDecoder;
class QAudioSink;
class QTimer;

namespace pyrrha {

class StreamBuffer;

// The native low-level engine: QAudioDecoder decodes to raw PCM that *we* own via
// a StreamBuffer, and QAudioSink plays it. Playback is now STREAMING — it starts
// as soon as the first audio is buffered rather than waiting for the whole file
// to decode, and a StreamBuffer in live mode can play an unbounded stream
// (internet radio) without growing memory. Owning the samples is also what makes
// the future DSP (EQ / ReplayGain / gapless) possible, with no GStreamer, no
// GLib.
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
    void maybeStartSink();   // start playback once there's audio + play was asked
    void startSink();
    void teardownSink();
    void setState(State state);

    QAudioDecoder *m_decoder;
    QAudioSink *m_sink = nullptr;
    StreamBuffer *m_stream;   // decoded PCM the sink pulls from
    QAudioFormat m_format;    // the device's preferred format (decode target)
    QTimer *m_posTimer;       // drives positionChanged while playing

    State m_state = State::Stopped;
    bool m_playRequested = false;   // play() arrived; start the sink when data is in
    qreal m_volume = 0.8;
};

}  // namespace pyrrha
