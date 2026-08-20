// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// Hosts the three classic skin windows — main + equalizer + playlist — on a
// skin, stacked Winamp-style, and wires them to the Player: the main window's
// transport drives playback (via ClassicController), its EQ/PL toggle buttons
// show/hide the other two, and the playlist mirrors the queue.
#pragma once

#include <QObject>
#include <QString>

namespace pyrrha {

class Player;
class SkinnedWindow;
class SkinnedEqWindow;
class SkinnedPlaylistWindow;
class ClassicController;

class SkinnedShell : public QObject {
    Q_OBJECT
public:
    explicit SkinnedShell(Player *player, QObject *parent = nullptr);
    ~SkinnedShell() override;

    bool loadSkin(const QString &path);   // into all three windows
    void show();

    SkinnedWindow *mainWindow() const { return m_main; }
    SkinnedEqWindow *eqWindow() const { return m_eq; }
    SkinnedPlaylistWindow *playlistWindow() const { return m_pl; }

private:
    void positionWindows();
    void refreshPlaylist();

    Player *m_player;
    SkinnedWindow *m_main;
    SkinnedEqWindow *m_eq;
    SkinnedPlaylistWindow *m_pl;
    ClassicController *m_ctl;
};

}  // namespace pyrrha
