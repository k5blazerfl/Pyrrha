// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "skin/SkinnedPlaylistWindow.h"

#include <QFont>
#include <QPainter>
#include <QPaintEvent>

namespace pyrrha {

using namespace coords::pl;

namespace {
QColor parseHex(const QString &s) {
    QString t = s.trimmed();
    if (!t.startsWith(QLatin1Char('#')))
        t.prepend(QLatin1Char('#'));
    return QColor(t);  // invalid if not a colour
}
}  // namespace

SkinnedPlaylistWindow::SkinnedPlaylistWindow(QWidget *parent) : QWidget(parent) {
    setWindowFlag(Qt::FramelessWindowHint);
    resize(kDefaultW, kDefaultH);
    // Winamp's classic playlist resizes vertically; keep the width fixed.
    setFixedWidth(kDefaultW);
}

void SkinnedPlaylistWindow::parseColors() {
    const QString txt = m_skin.text(QStringLiteral("pledit.txt"));
    for (QString line : txt.split(QLatin1Char('\n'))) {
        line = line.trimmed();
        const int eq = line.indexOf(QLatin1Char('='));
        if (eq < 0)
            continue;
        const QString k = line.left(eq).trimmed().toLower();
        const QColor c = parseHex(line.mid(eq + 1));
        if (!c.isValid())
            continue;
        if (k == QLatin1String("normal"))
            m_cNormal = c;
        else if (k == QLatin1String("current"))
            m_cCurrent = c;
        else if (k == QLatin1String("normalbg"))
            m_cBg = c;
        else if (k == QLatin1String("selectedbg"))
            m_cSelBg = c;
    }
}

bool SkinnedPlaylistWindow::loadSkin(const QString &path) {
    if (!m_skin.load(path))
        return false;
    parseColors();
    update();
    return true;
}

void SkinnedPlaylistWindow::setRows(const QStringList &titles,
                                    const QStringList &durations) {
    m_titles = titles;
    m_durations = durations;
    m_scroll = 0;
    update();
}

void SkinnedPlaylistWindow::setCurrentRow(int i) {
    m_current = i;
    update();
}

void SkinnedPlaylistWindow::blitTitlebar(QPainter &p, int w) {
    auto S = [&](const coords::Rect &r) {
        return m_skin.sprite(QStringLiteral("pledit.bmp"), r.x, r.y, r.w, r.h);
    };
    for (int x = kTitleLeft.w; x < w - kTitleRight.w; x += kTitleFill.w)
        p.drawImage(x, 0, S(kTitleFill));
    p.drawImage(0, 0, S(kTitleLeft));
    p.drawImage(w - kTitleRight.w, 0, S(kTitleRight));
    p.drawImage((w - kTitleCentre.w) / 2, 0, S(kTitleCentre));
}

void SkinnedPlaylistWindow::blitFrame(QPainter &p, int w, int lh) {
    auto S = [&](const coords::Rect &r) {
        return m_skin.sprite(QStringLiteral("pledit.bmp"), r.x, r.y, r.w, r.h);
    };
    for (int y = kTitleH; y < lh - kFrameB; y += kEdgeTileH) {
        p.drawImage(0, y, S(kEdgeLeft));
        p.drawImage(w - kFrameR, y, S(kEdgeRight));
    }
    const int by = lh - kFrameB;
    for (int x = kBottomLeft.w; x < w - kBottomRight.w; x += kBottomFill.w)
        p.drawImage(x, by, S(kBottomFill));
    p.drawImage(0, by, S(kBottomLeft));
    p.drawImage(w - kBottomRight.w, by, S(kBottomRight));
}

void SkinnedPlaylistWindow::drawRows(QPainter &p, int w, int lh) {
    QFont f = p.font();
    f.setPixelSize(kRowH - 3);
    p.setFont(f);
    const int rowW = w - kFrameL - kFrameR;
    const int listBottom = lh - kFrameB;
    int y = kListTop;
    for (int i = m_scroll; i < m_titles.size() && y + kRowH <= listBottom; ++i) {
        const QRect row(kFrameL, y, rowW, kRowH);
        if (i == m_current) {
            p.fillRect(row, m_cSelBg);
            p.setPen(m_cCurrent);
        } else {
            p.setPen(m_cNormal);
        }
        const QRect text = row.adjusted(2, 0, -2, 0);
        p.drawText(text, Qt::AlignVCenter | Qt::AlignLeft,
                   QStringLiteral("%1. %2").arg(i + 1).arg(m_titles[i]));
        if (i < m_durations.size())
            p.drawText(text, Qt::AlignVCenter | Qt::AlignRight, m_durations[i]);
        y += kRowH;
    }
}

void SkinnedPlaylistWindow::paintEvent(QPaintEvent *) {
    QPainter p(this);
    if (!m_skin.isValid()) {
        p.fillRect(rect(), Qt::black);
        return;
    }
    const int w = width();
    const int lh = height();
    p.fillRect(QRect(kFrameL, kTitleH, w - kFrameL - kFrameR, lh - kTitleH - kFrameB),
               m_cBg);
    blitTitlebar(p, w);
    blitFrame(p, w, lh);
    drawRows(p, w, lh);
}

}  // namespace pyrrha
