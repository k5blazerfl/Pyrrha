// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// Drives synthetic mouse events at the classic main window's button/slider
// coordinates and checks the right signals fire (with the right values) — the
// interaction contract, verifiable without a display (offscreen platform).
#include <cstdio>

#include <QApplication>
#include <QFileInfo>
#include <QSignalSpy>
#include <QTest>

#include "skin/SkinCoords.h"
#include "skin/SkinnedWindow.h"

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
static QPoint centre(const coords::Button &b) { return {b.dx + b.w / 2, b.dy + b.h / 2}; }

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    if (!QFileInfo::exists(
            QStringLiteral("/home/charron/py-pyrrha/pyrrha/skins/Glare"))) {
        std::printf("SKIP: test skins not present\n");
        return 0;
    }
    SkinnedWindow w;
    CHECK(w.loadSkin(QStringLiteral("/home/charron/py-pyrrha/pyrrha/skins/Glare")));
    w.show();

    QSignalSpy playSpy(&w, &SkinnedWindow::playClicked);
    QSignalSpy stopSpy(&w, &SkinnedWindow::stopClicked);
    QSignalSpy nextSpy(&w, &SkinnedWindow::nextClicked);
    QSignalSpy closeSpy(&w, &SkinnedWindow::closeClicked);
    QSignalSpy volSpy(&w, &SkinnedWindow::volumeChanged);
    QSignalSpy seekSpy(&w, &SkinnedWindow::seekRequested);
    QSignalSpy balSpy(&w, &SkinnedWindow::balanceChanged);

    using namespace coords;
    QTest::mouseClick(&w, Qt::LeftButton, {}, centre(kButtons[1]));  // play
    CHECK(playSpy.count() == 1);
    QTest::mouseClick(&w, Qt::LeftButton, {}, centre(kButtons[3]));  // stop
    CHECK(stopSpy.count() == 1);
    QTest::mouseClick(&w, Qt::LeftButton, {}, centre(kButtons[4]));  // next
    CHECK(nextSpy.count() == 1);
    QTest::mouseClick(&w, Qt::LeftButton, {}, centre(kCloseBtn));    // close
    CHECK(closeSpy.count() == 1);

    // A press that starts on a button but releases off it must NOT fire.
    QTest::mousePress(&w, Qt::LeftButton, {}, centre(kButtons[1]));
    QTest::mouseRelease(&w, Qt::LeftButton, {}, QPoint(0, 60));  // released away
    CHECK(playSpy.count() == 1);  // still 1

    // Volume slider near the left → a low volume.
    QTest::mouseClick(&w, Qt::LeftButton, {},
                      QPoint(kVolumeX + 2, kVolumeY + kVolumeH / 2));
    CHECK(volSpy.count() >= 1);
    if (volSpy.count())
        CHECK(volSpy.last().at(0).toDouble() < 0.2);

    // Seek near the middle → ~0.5.
    QTest::mouseClick(&w, Qt::LeftButton, {},
                      QPoint(kPosbarX + kPosbarW / 2, kPosbarY + kPosbarH / 2));
    CHECK(seekSpy.count() >= 1);
    if (seekSpy.count()) {
        const double f = seekSpy.last().at(0).toDouble();
        CHECK(f > 0.4 && f < 0.6);
    }

    // Balance at centre → snaps to 0.
    QTest::mouseClick(&w, Qt::LeftButton, {},
                      QPoint(kBalanceX + kBalanceW / 2, kBalanceY + kBalanceH / 2));
    CHECK(balSpy.count() >= 1);
    if (balSpy.count())
        CHECK(qAbs(balSpy.last().at(0).toDouble()) < 0.001);

    if (g_failed == 0)
        std::printf("SkinnedWindow interaction: all tests passed\n");
    else
        std::fprintf(stderr, "SkinnedWindow interaction: %d failed\n", g_failed);
    return g_failed == 0 ? 0 : 1;
}
