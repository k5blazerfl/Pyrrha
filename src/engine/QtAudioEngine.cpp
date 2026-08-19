// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "engine/QtAudioEngine.h"

#include <QAudioBuffer>
#include <QAudioDecoder>
#include <QAudioSink>
#include <QBuffer>
#include <QMediaDevices>
#include <QTimer>

namespace pyrrha {

QtAudioEngine::QtAudioEngine(QObject *parent)
    : PlayerEngine(parent), m_decoder(new QAudioDecoder(this)),
      m_posTimer(new QTimer(this)) {
    connect(m_decoder, &QAudioDecoder::bufferReady, this,
            &QtAudioEngine::onBufferReady);
    connect(m_decoder, &QAudioDecoder::finished, this,
            &QtAudioEngine::onDecodeFinished);
    connect(m_decoder, &QAudioDecoder::durationChanged, this,
            [this](qint64 ms) { emit durationChanged(ms); });
    connect(m_decoder, qOverload<QAudioDecoder::Error>(&QAudioDecoder::error),
            this,
            [this](QAudioDecoder::Error) { emit error(m_decoder->errorString()); });

    m_posTimer->setInterval(200);
    connect(m_posTimer, &QTimer::timeout, this,
            [this] { emit positionChanged(position()); });
}

QtAudioEngine::~QtAudioEngine() { teardownSink(); }

void QtAudioEngine::load(const QUrl &url) {
    teardownSink();
    m_pcm.clear();
    m_ready = false;
    m_playRequested = false;
    setState(State::Stopped);

    // Decode straight to the output device's preferred format, so the sink is
    // guaranteed to accept it (no resampling dance, no format-mismatch failure).
    // Fall back to a standard CD format when there is no output device yet (e.g.
    // a headless run) so decoding — and duration/position — still work.
    m_format = QMediaDevices::defaultAudioOutput().preferredFormat();
    if (!m_format.isValid()) {
        m_format.setSampleRate(44100);
        m_format.setChannelCount(2);
        m_format.setSampleFormat(QAudioFormat::Int16);
    }
    m_decoder->stop();
    m_decoder->setAudioFormat(m_format);
    m_decoder->setSource(url);
    m_decoder->start();
}

void QtAudioEngine::onBufferReady() {
    const QAudioBuffer buf = m_decoder->read();
    if (buf.isValid())
        m_pcm.append(buf.constData<char>(), buf.byteCount());
}

void QtAudioEngine::onDecodeFinished() {
    m_ready = true;
    emit durationChanged(duration());
    if (m_playRequested) {
        m_playRequested = false;
        startSink();
    }
}

void QtAudioEngine::play() {
    if (m_state == State::Paused && m_sink) {
        m_sink->resume();
        m_posTimer->start();
        setState(State::Playing);
        return;
    }
    if (m_ready)
        startSink();
    else
        m_playRequested = true;  // decoding still running — start when it finishes
}

void QtAudioEngine::pause() {
    if (m_state == State::Playing && m_sink) {
        m_sink->suspend();
        m_posTimer->stop();
        setState(State::Paused);
    }
}

void QtAudioEngine::stop() {
    m_playRequested = false;
    teardownSink();
    setState(State::Stopped);
}

void QtAudioEngine::startSink() {
    teardownSink();
    if (!m_format.isValid() || m_pcm.isEmpty())
        return;
    if (QMediaDevices::defaultAudioOutput().isNull()) {
        emit error(QStringLiteral("No audio output device available."));
        return;
    }

    m_pcmDevice = new QBuffer(&m_pcm, this);
    m_pcmDevice->open(QIODevice::ReadOnly);

    m_sink = new QAudioSink(m_format, this);
    m_sink->setVolume(m_volume);
    connect(m_sink, &QAudioSink::stateChanged, this, [this](QAudio::State s) {
        // The buffer running dry at end-of-track lands the sink in IdleState;
        // guard on Playing so we report the end exactly once.
        if (s == QAudio::IdleState && m_pcmDevice && m_pcmDevice->atEnd() &&
            m_state == State::Playing) {
            setState(State::Stopped);
            emit trackEnded();
        }
    });
    m_sink->start(m_pcmDevice);
    m_posTimer->start();
    setState(State::Playing);
}

void QtAudioEngine::teardownSink() {
    m_posTimer->stop();
    if (m_sink) {
        m_sink->stop();
        m_sink->deleteLater();
        m_sink = nullptr;
    }
    if (m_pcmDevice) {
        m_pcmDevice->close();
        m_pcmDevice->deleteLater();
        m_pcmDevice = nullptr;
    }
}

void QtAudioEngine::seek(qint64 ms) {
    if (!m_pcmDevice || !m_format.isValid())
        return;
    const qint64 want = m_format.bytesForDuration(ms * 1000);
    const qint64 maxBytes = static_cast<qint64>(m_pcm.size());
    qint64 bytes = qBound<qint64>(0, want, maxBytes);
    const int frame = m_format.bytesPerFrame();
    if (frame > 0)
        bytes -= bytes % frame;  // align to a sample-frame boundary
    m_pcmDevice->seek(bytes);
    emit positionChanged(position());
}

void QtAudioEngine::setVolume(qreal volume) {
    m_volume = qBound(0.0, volume, 1.0);
    if (m_sink)
        m_sink->setVolume(m_volume);
}

qint64 QtAudioEngine::position() const {
    if (!m_pcmDevice || !m_format.isValid())
        return 0;
    return m_format.durationForBytes(m_pcmDevice->pos()) / 1000;
}

qint64 QtAudioEngine::duration() const {
    if (m_ready && m_format.isValid())
        return m_format.durationForBytes(m_pcm.size()) / 1000;
    return m_decoder ? m_decoder->duration() : 0;
}

void QtAudioEngine::setState(State state) {
    if (state == m_state)
        return;
    m_state = state;
    emit stateChanged(m_state);
}

}  // namespace pyrrha
