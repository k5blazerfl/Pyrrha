// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "ui/SkinnedShell.h"

#include "model/Track.h"
#include "player/Player.h"
#include "skin/SkinCoords.h"
#include "skin/SkinnedEqWindow.h"
#include "skin/SkinnedPlaylistWindow.h"
#include "skin/SkinnedWindow.h"
#include "ui/ClassicController.h"

namespace pyrrha {

SkinnedShell::SkinnedShell(Player *player, QObject *parent)
    : QObject(parent), m_player(player), m_main(new SkinnedWindow),
      m_eq(new SkinnedEqWindow), m_pl(new SkinnedPlaylistWindow) {
    m_ctl = new ClassicController(m_main, player, this);

    // The main window's EQ / PL toggles show or hide the other two windows.
    connect(m_main, &SkinnedWindow::eqToggleClicked, this,
            [this] { m_eq->setVisible(!m_eq->isVisible()); });
    connect(m_main, &SkinnedWindow::plToggleClicked, this,
            [this] { m_pl->setVisible(!m_pl->isVisible()); });
    connect(m_main, &SkinnedWindow::closeClicked, this, [this] {
        m_main->close();
        m_eq->close();
        m_pl->close();
    });
    connect(m_eq, &SkinnedEqWindow::closeClicked, m_eq, &QWidget::hide);
    connect(m_pl, &SkinnedPlaylistWindow::closeClicked, m_pl, &QWidget::hide);

    // Double-clicking a playlist row plays it.
    connect(m_pl, &SkinnedPlaylistWindow::rowActivated, this,
            [this](int i) { m_player->playIndex(i); });

    // The playlist mirrors the queue.
    connect(player, &Player::queueChanged, this, [this] { refreshPlaylist(); });
    connect(player, &Player::currentChanged, this, [this] { refreshPlaylist(); });
    refreshPlaylist();
}

SkinnedShell::~SkinnedShell() {
    delete m_main;   // the three windows are top-level, not QObject-parented
    delete m_eq;
    delete m_pl;
}

bool SkinnedShell::loadSkin(const QString &path) {
    const bool ok = m_main->loadSkin(path);
    // TODO: share one Skin across the three windows instead of parsing thrice.
    m_eq->loadSkin(path);
    m_pl->loadSkin(path);
    positionWindows();
    return ok;
}

void SkinnedShell::positionWindows() {
    QPoint origin = m_main->pos();
    if (origin.isNull())
        origin = QPoint(120, 120);
    m_main->move(origin);
    m_eq->move(origin.x(), origin.y() + coords::kH);                    // below main
    m_pl->move(origin.x(), origin.y() + coords::kH + coords::eq::kH);   // below EQ
}

void SkinnedShell::show() {
    m_main->show();
    m_eq->show();
    m_pl->show();
    positionWindows();
    m_main->raise();
}

void SkinnedShell::refreshPlaylist() {
    QStringList titles;
    QStringList durations;
    for (const Track &t : m_player->queue()) {
        titles << t.displayTitle();
        if (t.durationMs > 0) {
            const qint64 s = t.durationMs / 1000;
            durations << QStringLiteral("%1:%2")
                             .arg(s / 60)
                             .arg(s % 60, 2, 10, QLatin1Char('0'));
        } else {
            durations << QString();
        }
    }
    m_pl->setRows(titles, durations);
    m_pl->setCurrentRow(m_player->currentIndex());
}

}  // namespace pyrrha
