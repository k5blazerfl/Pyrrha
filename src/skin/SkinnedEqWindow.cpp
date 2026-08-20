// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "skin/SkinnedEqWindow.h"

#include <QMouseEvent>
#include <QPainter>
#include <QPaintEvent>
#include <QWindow>

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

    // The dragged slider shows the pressed thumb sprite (kThumbSrcYDrag).
    auto thumb = [&](int slider) {
        const int sy = (slider == m_dragSlider) ? kThumbSrcYDrag : kThumbSrcY;
        return m_skin->sprite(QStringLiteral("eqmain.bmp"), kThumbSrcX, sy,
                              kThumbW, kThumbH);
    };
    p.drawImage(sliderX(0), thumbY(m_preamp), thumb(0));           // preamp
    for (int i = 0; i < kBands; ++i)
        p.drawImage(sliderX(i + 1), thumbY(m_bands[i]), thumb(i + 1));  // bands
}

int SkinnedEqWindow::sliderAt(const QPoint &pt) const {
    using namespace coords::eq;
    if (pt.y() < kSliderTop || pt.y() > kSliderTop + kSliderTravel + kThumbH)
        return -1;
    for (int i = 0; i <= kBands; ++i) {
        const int x = sliderX(i);
        if (pt.x() >= x && pt.x() < x + kThumbW)
            return i;
    }
    return -1;
}

void SkinnedEqWindow::applySliderDrag(int slider, int y) {
    using namespace coords::eq;
    // Invert thumbY (grab the thumb by its centre); g in [-1, 1], +1 = top/boost.
    qreal g = 1.0 - 2.0 * qreal(y - kThumbH / 2 - kSliderTop) / kSliderTravel;
    g = qBound(-1.0, g, 1.0);
    if (slider == 0) {
        setPreamp(g);
        emit preampChanged(g);
    } else {
        setBand(slider - 1, g);
        emit bandChanged(slider - 1, g);
    }
}

void SkinnedEqWindow::mousePressEvent(QMouseEvent *e) {
    if (e->button() != Qt::LeftButton) {
        QWidget::mousePressEvent(e);
        return;
    }
    const QPoint pt = e->position().toPoint();
    if (coords::eq::kCloseBtn.contains(pt.x(), pt.y())) {
        emit closeClicked();
        return;
    }
    const int s = sliderAt(pt);
    if (s >= 0) {
        m_dragSlider = s;
        applySliderDrag(s, pt.y());
        return;
    }
    // Titlebar drag → let the compositor move the frameless window (Wayland).
    if (pt.y() < 14 && windowHandle()) {
        windowHandle()->startSystemMove();
        return;
    }
    QWidget::mousePressEvent(e);
}

void SkinnedEqWindow::mouseMoveEvent(QMouseEvent *e) {
    if (m_dragSlider >= 0)
        applySliderDrag(m_dragSlider, e->position().toPoint().y());
    else
        QWidget::mouseMoveEvent(e);
}

void SkinnedEqWindow::mouseReleaseEvent(QMouseEvent *e) {
    if (m_dragSlider >= 0) {
        m_dragSlider = -1;
        update();
    }
    QWidget::mouseReleaseEvent(e);
}

}  // namespace pyrrha
