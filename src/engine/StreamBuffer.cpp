// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "engine/StreamBuffer.h"

#include <QMutexLocker>
#include <cstring>

namespace pyrrha {

namespace {
// In live mode, discard already-played audio from the front once this much has
// accumulated (keeps memory bounded without copying on every tiny read).
constexpr qint64 kTrimThreshold = 256 * 1024;
}  // namespace

StreamBuffer::StreamBuffer(QObject *parent) : QIODevice(parent) {}

void StreamBuffer::start(bool seekable) {
    {
        QMutexLocker lock(&m_mutex);
        m_store.clear();
        m_storeBase = 0;
        m_consumed = 0;
        m_written = 0;
        m_finished = false;
        m_seekable = seekable;
    }
    if (isOpen())
        close();
    // Unbuffered: the sink's reads map straight to readData(), so we control
    // chunking and there's no stale QIODevice buffer to reason about on seek.
    open(QIODevice::ReadOnly | QIODevice::Unbuffered);
}

void StreamBuffer::appendPcm(const char *data, qint64 len) {
    if (len <= 0)
        return;
    QMutexLocker lock(&m_mutex);
    m_store.append(data, len);
    m_written += len;
}

void StreamBuffer::setFinished() {
    QMutexLocker lock(&m_mutex);
    m_finished = true;
}

bool StreamBuffer::seekToByte(qint64 pos) {
    QMutexLocker lock(&m_mutex);
    if (!m_seekable)
        return false;
    m_consumed = qBound<qint64>(0, pos, m_storeBase + m_store.size());
    return true;
}

qint64 StreamBuffer::consumed() const {
    QMutexLocker lock(&m_mutex);
    return m_consumed;
}

qint64 StreamBuffer::totalWritten() const {
    QMutexLocker lock(&m_mutex);
    return m_written;
}

qint64 StreamBuffer::buffered() const {
    QMutexLocker lock(&m_mutex);
    return (m_storeBase + m_store.size()) - m_consumed;
}

bool StreamBuffer::finished() const {
    QMutexLocker lock(&m_mutex);
    return m_finished;
}

bool StreamBuffer::atEnd() const {
    QMutexLocker lock(&m_mutex);
    return m_finished && m_consumed >= m_storeBase + m_store.size();
}

qint64 StreamBuffer::bytesAvailable() const {
    QMutexLocker lock(&m_mutex);
    const qint64 real = (m_storeBase + m_store.size()) - m_consumed;
    // While more data is still coming, keep the sink pulling even during a brief
    // underrun (readData will hand it silence) so playback never hard-stalls.
    return real + (m_finished ? 0 : 4096) + QIODevice::bytesAvailable();
}

qint64 StreamBuffer::readData(char *out, qint64 maxSize) {
    if (maxSize <= 0)
        return 0;
    QMutexLocker lock(&m_mutex);
    const qint64 idx = m_consumed - m_storeBase;   // index into m_store
    const qint64 avail = m_store.size() - idx;     // real bytes available
    if (avail <= 0) {
        if (m_finished)
            return 0;                              // true EOF → sink idles → ended
        std::memset(out, 0, maxSize);              // underrun → silence, hold pos
        return maxSize;
    }
    const qint64 real = qMin(avail, maxSize);
    std::memcpy(out, m_store.constData() + idx, real);
    m_consumed += real;                            // only real audio advances pos
    if (!m_seekable)
        trimLocked();
    if (real < maxSize && !m_finished) {
        std::memset(out + real, 0, maxSize - real);  // pad the tail with silence
        return maxSize;
    }
    return real;
}

void StreamBuffer::trimLocked() {
    const qint64 played = m_consumed - m_storeBase;
    if (played > kTrimThreshold) {
        m_store.remove(0, static_cast<int>(played));
        m_storeBase = m_consumed;
    }
}

}  // namespace pyrrha
