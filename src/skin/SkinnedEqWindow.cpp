// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "skin/SkinnedEqWindow.h"

#include <QPainter>
#include <QPaintEvent>

namespace pyrrha {

SkinnedEqWindow::SkinnedEqWindow(QWidget *parent) : QWidget(parent) {
    setWindowFlag(Qt::FramelessWindowHint);
    setFixedSize(coords::eq::kW, coords::eq::kH);
}

bool SkinnedEqWindow::loadSkin(const QString &path) {
    auto skin = std::make_shared<Skin>();
    if (!skin->load(path))
        return false;
    setSkin(std::move(skin));
    return true;
}

void SkinnedEqWindow::setSkin(std::shared_ptr<Skin> skin) {
    m_skin = std::move(skin);
    const QRegion shape = m_skin->region(QStringLiteral("equalizer"));
    if (!shape.isEmpty())
        setMask(shape);
    else
        clearMask();
    update();
}

void SkinnedEqWindow::setPreamp(qreal g) {
    m_preamp = qBound(-1.0, g, 1.0);
    update();
}

void SkinnedEqWindow::setBand(int i, qreal g) {
    if (i >= 0 && i < coords::eq::kBands) {
        m_bands[i] = qBound(-1.0, g, 1.0);
        update();
    }
}

void SkinnedEqWindow::setBands(const std::array<qreal, coords::eq::kBands> &g) {
    for (int i = 0; i < coords::eq::kBands; ++i)
        m_bands[i] = qBound(-1.0, g[i], 1.0);
    update();
}

void SkinnedEqWindow::paintEvent(QPaintEvent *) {
    QPainter p(this);
    if (!m_skin || !m_skin->isValid()) {
        p.fillRect(rect(), Qt::black);
        return;
    }
    using namespace coords::eq;

    // The EQ face (titlebar, graph area, slider grooves, ON/AUTO/Presets) is the
    // top of eqmain.bmp.
    p.drawImage(0, 0, m_skin->sprite(QStringLiteral("eqmain.bmp"), 0, 0, kW, kH));

    const QImage thumb =
        m_skin->sprite(QStringLiteral("eqmain.bmp"), kThumbSrcX, kThumbSrcY,
                      kThumbW, kThumbH);
    p.drawImage(sliderX(0), thumbY(m_preamp), thumb);           // preamp
    for (int i = 0; i < kBands; ++i)
        p.drawImage(sliderX(i + 1), thumbY(m_bands[i]), thumb);  // the ten bands
}

}  // namespace pyrrha
