// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// Verifies the skin loader + bitmap fonts against the real py-pyrrha test skins
// (the unpacked Glare skin and a .wsz archive). QImage/QPainter work without a
// QGuiApplication, so this stays a plain program.
#include <cstdio>

#include <QFileInfo>
#include <QImage>

#include "skin/BitmapFont.h"
#include "skin/Skin.h"

using namespace pyrrha;

static int g_failed = 0;
#define CHECK(cond)                                                      \
    do {                                                                 \
        if (!(cond)) {                                                   \
            std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #cond); \
            ++g_failed;                                                  \
        }                                                                \
    } while (0)

int main() {
    const QString glare =
        QStringLiteral("/home/charron/py-pyrrha/pyrrha/skins/Glare");
    const QString wsz =
        QStringLiteral("/home/charron/py-pyrrha/themes/base-2.91.wsz");

    if (!QFileInfo::exists(glare)) {
        std::fprintf(stderr, "SKIP: test skins not present\n");
        return 0;  // don't fail CI if the legacy repo isn't checked out
    }

    // -- unpacked directory skin --------------------------------------------
    Skin dir;
    CHECK(dir.load(glare));
    CHECK(dir.isValid());
    CHECK(dir.has(QStringLiteral("main.bmp")));
    CHECK(dir.has(QStringLiteral("MAIN.BMP")));  // case-insensitive

    const QImage main = dir.image(QStringLiteral("main.bmp"));
    CHECK(!main.isNull());
    CHECK(main.width() == 275 && main.height() == 116);

    const QImage btn = dir.sprite(QStringLiteral("cbuttons.bmp"), 0, 0, 23, 18);
    CHECK(!btn.isNull() && btn.width() == 23 && btn.height() == 18);

    // Out-of-bounds sprite → correct size, transparent padding (not black).
    const QImage oob = dir.sprite(QStringLiteral("main.bmp"), 270, 110, 20, 20);
    CHECK(oob.width() == 20 && oob.height() == 20);
    CHECK(oob.pixelColor(19, 19).alpha() == 0);

    // -- bitmap fonts -------------------------------------------------------
    const TextFont tf(&dir);
    const QImage title = tf.render(QStringLiteral("PYRRHA"));
    CHECK(title.width() == 6 * TextFont::CharW && title.height() == TextFont::CharH);

    const NumberFont nf(&dir);
    const QImage d5 = nf.digit(QLatin1Char('5'));
    CHECK(d5.width() == NumberFont::NumW && d5.height() == NumberFont::NumH);
    const QImage minus = nf.digit(QLatin1Char('-'));  // Glare nums_ex = 12 cells
    CHECK(minus.width() == NumberFont::NumW && minus.height() == NumberFont::NumH);

    // -- .wsz archive skin --------------------------------------------------
    if (QFileInfo::exists(wsz)) {
        Skin zip;
        CHECK(zip.load(wsz));
        CHECK(zip.isValid());
        CHECK(zip.has(QStringLiteral("main.bmp")));
        CHECK(zip.image(QStringLiteral("main.bmp")).width() == 275);
    }

    if (g_failed == 0)
        std::printf("Skin: all tests passed\n");
    else
        std::fprintf(stderr, "Skin: %d check(s) failed\n", g_failed);
    return g_failed == 0 ? 0 : 1;
}
