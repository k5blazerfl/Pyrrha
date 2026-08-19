// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "engine/QtMultimediaEngine.h"

#include <QAudioOutput>
#include <QMediaPlayer>

namespace pyrrha {

QtMultimediaEngine::QtMultimediaEngine(QObject *parent)
    : PlayerEngine(parent),
      m_player(new QMediaPlayer(this)),
      m_output(new QAudioOutput(this)) {
    m_player->setAudioOutput(m_output);

    connect(m_player, &QMediaPlayer::positionChanged, this,
            &PlayerEngine::positionChanged);
    connect(m_player, &QMediaPlayer::durationChanged, this,
            &PlayerEngine::durationChanged);

    connect(m_player, &QMediaPlayer::playbackStateChanged, this,
            [this](QMediaPlayer::PlaybackState s) {
                switch (s) {
                    case QMediaPlayer::PlayingState: m_state = State::Playing; break;
                    case QMediaPlayer::PausedState:  m_state = State::Paused;  break;
                    case QMediaPlayer::StoppedState: m_state = State::Stopped; break;
                }
                emit stateChanged(m_state);
            });

    connect(m_player, &QMediaPlayer::mediaStatusChanged, this,
            [this](QMediaPlayer::MediaStatus status) {
                if (status == QMediaPlayer::EndOfMedia)
                    emit trackEnded();
            });

    connect(m_player, &QMediaPlayer::errorOccurred, this,
            [this](QMediaPlayer::Error, const QString &msg) { emit error(msg); });
}

QtMultimediaEngine::~QtMultimediaEngine() = default;

void QtMultimediaEngine::load(const QUrl &url) { m_player->setSource(url); }
void QtMultimediaEngine::play() { m_player->play(); }
void QtMultimediaEngine::pause() { m_player->pause(); }
void QtMultimediaEngine::stop() { m_player->stop(); }
void QtMultimediaEngine::seek(qint64 ms) { m_player->setPosition(ms); }

void QtMultimediaEngine::setVolume(qreal volume) {
    m_output->setVolume(static_cast<float>(qBound(0.0, volume, 1.0)));
}

qint64 QtMultimediaEngine::position() const { return m_player->position(); }
qint64 QtMultimediaEngine::duration() const { return m_player->duration(); }

}  // namespace pyrrha
