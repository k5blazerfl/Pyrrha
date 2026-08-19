// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "skin/SkinnedWindow.h"

#include <QPainter>
#include <QPaintEvent>

namespace pyrrha {

SkinnedWindow::SkinnedWindow(QWidget *parent) : QWidget(parent) {
    setWindowFlag(Qt::FramelessWindowHint);
    setFixedSize(coords::kW, coords::kH);
}

bool SkinnedWindow::loadSkin(const QString &path) {
    if (!m_skin.load(path))
        return false;
    m_text.emplace(&m_skin);
    m_num.emplace(&m_skin);
    const QRegion shape = m_skin.region(QStringLiteral("normal"));
    if (!shape.isEmpty())
        setMask(shape);   // shaped skin
    else
        clearMask();
    update();
    return true;
}

void SkinnedWindow::setTitle(const QString &title) {
    m_title = title;
    update();
}
void SkinnedWindow::setTimeMs(qint64 ms) {
    m_timeMs = ms;
    update();
}
void SkinnedWindow::setDurationMs(qint64 ms) {
    m_durationMs = ms;
    update();
}
void SkinnedWindow::setPlaying(bool playing) {
    m_playing = playing;
    update();
}
void SkinnedWindow::setVolume(qreal v) {
    m_volume = qBound(0.0, v, 1.0);
    update();
}
void SkinnedWindow::setBalance(qreal b) {
    m_balance = qBound(-1.0, b, 1.0);
    update();
}

void SkinnedWindow::paintEvent(QPaintEvent *) {
    QPainter p(this);
    if (!m_skin.isValid()) {
        p.fillRect(rect(), Qt::black);
        return;
    }
    using namespace coords;

    p.drawImage(0, 0, m_skin.image(QStringLiteral("main.bmp")));
    p.drawImage(0, 0,
                m_skin.sprite(QStringLiteral("titlebar.bmp"), kTitlebarSrcX,
                              kTitlebarActiveY, kTitlebarW, kTitlebarH));

    for (const Button &b : kButtons)
        p.drawImage(b.dx, b.dy,
                    m_skin.sprite(QStringLiteral("cbuttons.bmp"), b.sx, b.sy0,
                                  b.w, b.h));

    p.drawImage(kStatusX, kStatusY,
                m_skin.sprite(QStringLiteral("playpaus.bmp"), m_playing ? 0 : 9,
                              0, 9, 9));

    const int vlevel = qRound(m_volume * 27);
    p.drawImage(kVolumeX, kVolumeY,
                m_skin.sprite(QStringLiteral("volume.bmp"), 0, vlevel * 15,
                              kVolumeW, kVolumeH));

    const int blevel = qRound(qAbs(m_balance) * 27);
    p.drawImage(kBalanceX, kBalanceY,
                m_skin.sprite(QStringLiteral("balance.bmp"), kBalanceSrcX,
                              blevel * 15, kBalanceW, kBalanceH));

    p.drawImage(kPosbarX, kPosbarY,
                m_skin.sprite(QStringLiteral("posbar.bmp"), 0, 0, kPosbarW,
                              kPosbarH));

    if (m_text)
        p.drawImage(kTitleX, kTitleY, m_text->render(m_title));

    drawTime(p);
}

void SkinnedWindow::drawTime(QPainter &p) const {
    if (!m_num)
        return;
    using namespace coords;
    const qint64 s = m_timeMs / 1000;
    const int mm = qMin<qint64>(99, s / 60);
    const int ss = int(s % 60);
    const QString d = QStringLiteral("%1%2")
                          .arg(mm, 2, 10, QLatin1Char('0'))
                          .arg(ss, 2, 10, QLatin1Char('0'));
    for (int i = 0; i < 4 && i < d.size(); ++i)
        p.drawImage(kTimeX[i], kTimeY, m_num->digit(d[i]));
}

}  // namespace pyrrha
