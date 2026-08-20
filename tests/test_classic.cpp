// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// Verifies classic-mode wiring: clicking the skin window's transport buttons and
// dragging its volume slider drives the real Player (via ClassicController).
// No audio hardware needed — next/previous/stop and volume are pure controller
// logic; the engine loading a bogus URL is a harmless async no-op.
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
#include "skin/SkinnedWindow.h"
#include "ui/ClassicController.h"

using namespace pyrrha;

static int g_failed = 0;
#define CHECK(cond)                                                      \
    do {                                                                 \
        if (!(cond)) {                                                   \
            std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #cond); \
            ++g_failed;                                                  \
        }                                                                \
    } while (0)

static QPoint centre(const coords::Button &b) { return {b.dx + b.w / 2, b.dy + b.h / 2}; }

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    if (!QFileInfo::exists(
            QStringLiteral("/home/charron/py-pyrrha/pyrrha/skins/Glare"))) {
        std::printf("SKIP: test skins not present\n");
        return 0;
    }
    QtAudioEngine engine;
    Player player(&engine);
    SkinnedWindow win;
    CHECK(win.loadSkin(QStringLiteral("/home/charron/py-pyrrha/pyrrha/skins/Glare")));
    ClassicController ctl(&win, &player);
    win.show();

    QVector<Track> q;
    for (int i = 0; i < 3; ++i) {
        Track t;
        t.title = QStringLiteral("Track %1").arg(i);
        t.url = QUrl(QStringLiteral("file:///tmp/none%1.ogg").arg(i));
        q.push_back(t);
    }
    player.setQueue(q);
    CHECK(player.currentIndex() == -1);

    using namespace coords;
    QTest::mouseClick(&win, Qt::LeftButton, {}, centre(kButtons[4]));  // next
    CHECK(player.currentIndex() == 0);
    QTest::mouseClick(&win, Qt::LeftButton, {}, centre(kButtons[4]));  // next
    CHECK(player.currentIndex() == 1);
    QTest::mouseClick(&win, Qt::LeftButton, {}, centre(kButtons[0]));  // prev
    CHECK(player.currentIndex() == 0);
    QTest::mouseClick(&win, Qt::LeftButton, {}, centre(kButtons[3]));  // stop
    CHECK(player.currentIndex() == -1);

    // Volume slider near the left → the controller lowers the player volume.
    QTest::mouseClick(&win, Qt::LeftButton, {},
                      QPoint(kVolumeX + 2, kVolumeY + kVolumeH / 2));
    CHECK(player.volume() < 0.2);

    if (g_failed == 0)
        std::printf("Classic wiring: all tests passed\n");
    else
        std::fprintf(stderr, "Classic wiring: %d failed\n", g_failed);
    return g_failed == 0 ? 0 : 1;
}
