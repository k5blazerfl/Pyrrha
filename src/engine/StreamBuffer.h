// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include <QByteArray>
#include <QIODevice>
#include <QMutex>

namespace pyrrha {

// The PCM buffer that sits between the decoder and the sink. Decoded audio is
// fed in with appendPcm() as it arrives; the QAudioSink pulls it via readData().
// This is what lets playback START before decoding finishes and — in live mode —
// play an unbounded stream (internet radio) by discarding audio once it has been
// played, so memory stays bounded.
//
// Sequential by design: the sink just keeps calling readData(); we serve from a
// "consumed bytes" cursor we control, so a seek is simply moving that cursor
// (keep-all / file mode only). An underrun returns silence rather than stalling
// the sink, and a true end-of-stream (finished + drained) returns 0 so the sink
// idles and the engine can report the track ended. Thread-safe: the sink backend
// may pull from its own thread while the decoder feeds from the main loop.
class StreamBuffer : public QIODevice {
    Q_OBJECT
public:
    explicit StreamBuffer(QObject *parent = nullptr);

    // (Re)open empty. seekable = keep every byte (a finite file: memory bounded
    // by the file, seeking works). !seekable = live: discard played audio, no
    // seek (an unbounded stream).
    void start(bool seekable);

    void appendPcm(const char *data, qint64 len);   // decoder feeds this
    void setFinished();                              // no more data is coming

    bool seekToByte(qint64 pos);   // keep-all only; clamps to [0, written]
    qint64 consumed() const;       // real bytes served — the position marker
    qint64 totalWritten() const;   // real bytes fed in so far
    qint64 buffered() const;       // real bytes ready to serve right now
    bool finished() const;
    bool atEnd() const override;   // finished && nothing left to serve

    bool isSequential() const override { return true; }
    qint64 bytesAvailable() const override;
    qint64 readData(char *data, qint64 maxSize) override;
    qint64 writeData(const char *, qint64) override { return -1; }  // read-only

private:
    void trimLocked();   // live mode: drop already-played bytes from the front

    mutable QMutex m_mutex;
    QByteArray m_store;
    qint64 m_storeBase = 0;   // stream offset of m_store[0]
    qint64 m_consumed = 0;    // total real bytes served
    qint64 m_written = 0;     // total real bytes appended
    bool m_seekable = true;
    bool m_finished = false;
};

}  // namespace pyrrha
