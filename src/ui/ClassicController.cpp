// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "ui/ClassicController.h"

#include <QWidget>

#include "engine/PlayerEngine.h"
#include "model/Track.h"
#include "player/Player.h"
#include "skin/SkinnedWindow.h"

namespace pyrrha {

ClassicController::ClassicController(SkinnedWindow *win, Player *player,
                                    QObject *parent)
    : QObject(parent), m_win(win), m_player(player),
      m_engine(player->engine()) {
    // -- window controls → player ------------------------------------------
    connect(win, &SkinnedWindow::prevClicked, player, &Player::previous);
    connect(win, &SkinnedWindow::nextClicked, player, &Player::next);
    connect(win, &SkinnedWindow::stopClicked, player, &Player::stop);
    connect(win, &SkinnedWindow::playClicked, this, [this] {
        if (m_engine->state() != PlayerEngine::State::Playing)
            m_player->togglePlayPause();   // resume, or start the current/first
    });
    connect(win, &SkinnedWindow::pauseClicked, this, [this] {
        if (m_engine->state() == PlayerEngine::State::Playing)
            m_player->togglePlayPause();
    });
    connect(win, &SkinnedWindow::seekRequested, this, [this](qreal frac) {
        const qint64 dur = m_engine->duration();
        if (dur > 0)
            m_player->seek(qint64(frac * dur));
    });
    connect(win, &SkinnedWindow::volumeChanged, player, &Player::setVolume);
    connect(win, &SkinnedWindow::closeClicked, win, &QWidget::close);

    // -- playback state → window -------------------------------------------
    connect(player, &Player::currentChanged, this,
            [this] { refreshNowPlaying(); });
    connect(m_engine, &PlayerEngine::positionChanged, win,
            &SkinnedWindow::setTimeMs);
    connect(m_engine, &PlayerEngine::durationChanged, win,
            &SkinnedWindow::setDurationMs);
    connect(m_engine, &PlayerEngine::stateChanged, this,
            [this](PlayerEngine::State s) {
                m_win->setPlaying(s == PlayerEngine::State::Playing);
            });

    win->setVolume(player->volume());
    refreshNowPlaying();
}

void ClassicController::refreshNowPlaying() {
    const Track *t = m_player->current();
    m_win->setTitle(t ? t->displayTitle().toUpper() : QStringLiteral("PYRRHA"));
    m_win->setPlaying(m_engine->state() == PlayerEngine::State::Playing);
}

}  // namespace pyrrha
