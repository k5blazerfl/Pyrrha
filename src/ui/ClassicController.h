// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// Bridges a SkinnedWindow (the classic skin UI) to the Player: the window's
// transport/slider signals drive playback, and playback state drives the
// window's display. This is what turns the skin *renderer* into a live UI — the
// payoff of the skin engine.
#pragma once

#include <QObject>

namespace pyrrha {

class SkinnedWindow;
class Player;
class PlayerEngine;

class ClassicController : public QObject {
    Q_OBJECT
public:
    ClassicController(SkinnedWindow *win, Player *player,
                      QObject *parent = nullptr);

private:
    void refreshNowPlaying();

    SkinnedWindow *m_win;
    Player *m_player;
    PlayerEngine *m_engine;
};

}  // namespace pyrrha
