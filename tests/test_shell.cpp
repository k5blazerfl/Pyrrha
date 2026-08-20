// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// Verifies the SkinnedShell hosts the three windows on a skin, the main window's
// EQ/PL toggles show/hide the other two, and the playlist mirrors the queue.
#include <cstdio>

#include <QApplication>
#include <QFileInfo>
#include <QTest>
#include <QUrl>
#include <QVector>

#include "engine/QtAudioEngine.h"
#include "model/Track.h"
#include "player/Player.h"
#include "skin/SkinCoords.h"
#include "skin/SkinnedEqWindow.h"
#include "skin/SkinnedPlaylistWindow.h"
#include "skin/SkinnedWindow.h"
#include "ui/SkinnedShell.h"

using namespace pyrrha;

static int g_failed = 0;
#define CHECK(cond)                                                      \
    do {                                                                 \
        if (!(cond)) {                                                   \
            std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #cond); \
            ++g_failed;                                                  \
        }                                                                \
    } while (0)

static QPoint centre(const coords::Rect &r) { return {r.x + r.w / 2, r.y + r.h / 2}; }

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    if (!QFileInfo::exists(
            QStringLiteral("/home/charron/py-pyrrha/pyrrha/skins/Glare"))) {
        std::printf("SKIP: test skins not present\n");
        return 0;
    }
    QtAudioEngine engine;
    Player player(&engine);
    QVector<Track> q;
    for (int i = 0; i < 4; ++i) {
        Track t;
        t.title = QStringLiteral("Song %1").arg(i);
        t.durationMs = (i + 1) * 60000;
        t.url = QUrl(QStringLiteral("file:///x%1.ogg").arg(i));
        q.push_back(t);
    }
    player.setQueue(q);

    SkinnedShell shell(&player);
    CHECK(shell.loadSkin(QStringLiteral("/home/charron/py-pyrrha/pyrrha/skins/Glare")));
    CHECK(shell.mainWindow()->hasSkin());
    CHECK(shell.eqWindow()->hasSkin());
    CHECK(shell.playlistWindow()->hasSkin());

    // The playlist mirrors the queue (populated in the shell ctor).
    CHECK(shell.playlistWindow()->rowCount() == 4);

    shell.show();
    CHECK(shell.eqWindow()->isVisible());
    CHECK(shell.playlistWindow()->isVisible());

    // Double-clicking a playlist row plays that track (row 2 of 4).
    const int rowY = coords::pl::kListTop + 2 * coords::pl::kRowH + 3;
    QTest::mouseDClick(shell.playlistWindow(), Qt::LeftButton, {}, QPoint(40, rowY));
    CHECK(player.currentIndex() == 2);

    // The EQ toggle on the main window hides / shows the EQ window.
    QTest::mouseClick(shell.mainWindow(), Qt::LeftButton, {}, centre(coords::kEqToggle));
    CHECK(!shell.eqWindow()->isVisible());
    QTest::mouseClick(shell.mainWindow(), Qt::LeftButton, {}, centre(coords::kEqToggle));
    CHECK(shell.eqWindow()->isVisible());

    // The PL toggle hides the playlist.
    QTest::mouseClick(shell.mainWindow(), Qt::LeftButton, {}, centre(coords::kPlToggle));
    CHECK(!shell.playlistWindow()->isVisible());

    if (g_failed == 0)
        std::printf("SkinnedShell: all tests passed\n");
    else
        std::fprintf(stderr, "SkinnedShell: %d failed\n", g_failed);
    return g_failed == 0 ? 0 : 1;
}
