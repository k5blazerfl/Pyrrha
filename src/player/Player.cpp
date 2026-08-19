// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "player/Player.h"

namespace pyrrha {

Player::Player(PlayerEngine *engine, QObject *parent)
    : QObject(parent), m_engine(engine) {
    // Advance to the next track when the current one ends naturally.
    connect(m_engine, &PlayerEngine::trackEnded, this, &Player::next);
}

void Player::setQueue(const QVector<Track> &tracks) {
    m_queue = tracks;
    m_index = -1;
    emit queueChanged();
    emit currentChanged(m_index);
}

void Player::updateTrack(int index, const Track &track) {
    if (index < 0 || index >= m_queue.size())
        return;
    m_queue[index] = track;
    if (index == m_index)
        emit currentChanged(m_index);  // refresh now-playing with real tags
}

const Track *Player::current() const {
    return (m_index >= 0 && m_index < m_queue.size()) ? &m_queue[m_index]
                                                      : nullptr;
}

void Player::loadAndPlay(int index) {
    m_index = index;
    m_engine->load(m_queue[index].url);
    m_engine->play();
    emit currentChanged(m_index);
}

void Player::playIndex(int index) {
    if (index < 0 || index >= m_queue.size())
        return;
    loadAndPlay(index);
}

void Player::togglePlayPause() {
    switch (m_engine->state()) {
        case PlayerEngine::State::Playing:
            m_engine->pause();
            break;
        case PlayerEngine::State::Paused:
            m_engine->play();
            break;
        case PlayerEngine::State::Stopped:
            // Nothing loaded yet: start from the current item, or the first.
            if (current())
                m_engine->play();
            else if (!m_queue.isEmpty())
                loadAndPlay(0);
            break;
    }
}

void Player::next() {
    if (m_queue.isEmpty())
        return;
    if (m_index + 1 < m_queue.size())
        loadAndPlay(m_index + 1);
    else
        stop();  // end of queue
}

void Player::previous() {
    if (m_queue.isEmpty())
        return;
    // If we're more than a few seconds in, restart the current track instead of
    // skipping back — the familiar transport behaviour.
    if (m_engine->position() > 3000) {
        m_engine->seek(0);
        return;
    }
    if (m_index > 0)
        loadAndPlay(m_index - 1);
    else
        m_engine->seek(0);
}

void Player::stop() {
    m_engine->stop();
    m_index = -1;
    emit currentChanged(m_index);
}

void Player::seek(qint64 ms) { m_engine->seek(ms); }
void Player::setVolume(qreal volume) { m_engine->setVolume(volume); }

}  // namespace pyrrha
