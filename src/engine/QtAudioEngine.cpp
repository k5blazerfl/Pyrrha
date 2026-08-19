// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "engine/QtAudioEngine.h"

#include <QAudioBuffer>
#include <QAudioDecoder>
#include <QAudioSink>
#include <QMediaDevices>
#include <QTimer>

#include "engine/StreamBuffer.h"

namespace pyrrha {

QtAudioEngine::QtAudioEngine(QObject *parent)
    : PlayerEngine(parent), m_decoder(new QAudioDecoder(this)),
      m_stream(new StreamBuffer(this)), m_posTimer(new QTimer(this)) {
    connect(m_decoder, &QAudioDecoder::bufferReady, this,
            &QtAudioEngine::onBufferReady);
    connect(m_decoder, &QAudioDecoder::finished, this,
            &QtAudioEngine::onDecodeFinished);
    connect(m_decoder, &QAudioDecoder::durationChanged, this,
            [this](qint64 ms) { emit durationChanged(ms); });
    connect(m_decoder, qOverload<QAudioDecoder::Error>(&QAudioDecoder::error),
            this, [this](QAudioDecoder::Error) {
                m_stream->setFinished();  // let the sink drain and end cleanly
                emit error(m_decoder->errorString());
            });

    m_posTimer->setInterval(200);
    connect(m_posTimer, &QTimer::timeout, this,
            [this] { emit positionChanged(position()); });
}

QtAudioEngine::~QtAudioEngine() { teardownSink(); }

void QtAudioEngine::load(const QUrl &url) {
    teardownSink();
    setState(State::Stopped);
    m_playRequested = false;

    // Decode to the output device's preferred format so the sink accepts it;
    // fall back to a standard CD format when there's no device (headless).
    m_format = QMediaDevices::defaultAudioOutput().preferredFormat();
    if (!m_format.isValid()) {
        m_format.setSampleRate(44100);
        m_format.setChannelCount(2);
        m_format.setSampleFormat(QAudioFormat::Int16);
    }
    m_stream->start(/*seekable=*/true);  // a local file: keep all, seeking works
    m_decoder->stop();
    m_decoder->setAudioFormat(m_format);
    m_decoder->setSource(url);
    m_decoder->start();
}

void QtAudioEngine::onBufferReady() {
    const QAudioBuffer buf = m_decoder->read();
    if (buf.isValid())
        m_stream->appendPcm(buf.constData<char>(), buf.byteCount());
    maybeStartSink();  // begin playback as soon as the first audio is in
}

void QtAudioEngine::onDecodeFinished() {
    m_stream->setFinished();
    emit durationChanged(duration());
    maybeStartSink();  // a very short clip: data + finished can arrive together
}

void QtAudioEngine::play() {
    if (m_state == State::Paused && m_sink) {
        m_sink->resume();
        m_posTimer->start();
        setState(State::Playing);
        return;
    }
    m_playRequested = true;
    maybeStartSink();
}

void QtAudioEngine::maybeStartSink() {
    if (m_playRequested && !m_sink && m_format.isValid() &&
        (m_stream->buffered() > 0 || m_stream->finished()))
        startSink();
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
    if (QMediaDevices::defaultAudioOutput().isNull()) {
        emit error(QStringLiteral("No audio output device available."));
        return;
    }
    m_playRequested = false;
    m_sink = new QAudioSink(m_format, this);
    m_sink->setVolume(m_volume);
    connect(m_sink, &QAudioSink::stateChanged, this, [this](QAudio::State s) {
        // The buffer only returns 0 (→ IdleState) at true end-of-stream; an
        // underrun is padded with silence and stays Active. Guard on Playing so
        // we report the end exactly once.
        if (s == QAudio::IdleState && m_stream->atEnd() &&
            m_state == State::Playing) {
            setState(State::Stopped);
            emit trackEnded();
        }
    });
    m_sink->start(m_stream);  // pull mode: the sink reads from the StreamBuffer
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
}

void QtAudioEngine::seek(qint64 ms) {
    if (!m_format.isValid())
        return;
    const qint64 bytes = m_format.bytesForDuration(ms * 1000);
    if (m_stream->seekToByte(bytes))
        emit positionChanged(position());
}

void QtAudioEngine::setVolume(qreal volume) {
    m_volume = qBound(0.0, volume, 1.0);
    if (m_sink)
        m_sink->setVolume(m_volume);
}

qint64 QtAudioEngine::position() const {
    if (!m_format.isValid())
        return 0;
    return m_format.durationForBytes(m_stream->consumed()) / 1000;
}

qint64 QtAudioEngine::duration() const {
    if (m_stream->finished() && m_format.isValid())
        return m_format.durationForBytes(m_stream->totalWritten()) / 1000;
    return m_decoder ? m_decoder->duration() : 0;
}

void QtAudioEngine::setState(State state) {
    if (state == m_state)
        return;
    m_state = state;
    emit stateChanged(m_state);
}

}  // namespace pyrrha
