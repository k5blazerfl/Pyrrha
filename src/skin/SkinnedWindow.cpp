// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "skin/SkinnedWindow.h"

#include <QMouseEvent>
#include <QPainter>
#include <QPaintEvent>
#include <QWindow>

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

    constexpr int nButtons = int(sizeof(kButtons) / sizeof(kButtons[0]));
    for (int i = 0; i < nButtons; ++i) {
        const Button &b = kButtons[i];
        const int sy = (i == m_pressedButton) ? b.sy1 : b.sy0;  // pressed state
        p.drawImage(b.dx, b.dy,
                    m_skin.sprite(QStringLiteral("cbuttons.bmp"), b.sx, sy, b.w,
                                  b.h));
    }

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

// -- interaction ------------------------------------------------------------

int SkinnedWindow::transportButtonAt(const QPoint &pt) const {
    constexpr int n = int(sizeof(coords::kButtons) / sizeof(coords::kButtons[0]));
    for (int i = 0; i < n; ++i)
        if (coords::buttonRect(coords::kButtons[i]).contains(pt.x(), pt.y()))
            return i;
    return -1;
}

void SkinnedWindow::updateSliderFromX(int x) {
    using namespace coords;
    switch (m_drag) {
        case Drag::Volume: {
            setVolume(qreal(x - kVolumeX) / kVolumeW);
            emit volumeChanged(m_volume);
            break;
        }
        case Drag::Balance: {
            qreal bal = qreal(x - kBalanceX) / kBalanceW * 2.0 - 1.0;
            if (qAbs(bal) < kBalSnap)
                bal = 0.0;  // snap to centre
            setBalance(bal);
            emit balanceChanged(m_balance);
            break;
        }
        case Drag::Seek: {
            const qreal frac = qBound(0.0, qreal(x - kPosbarX) / kPosbarW, 1.0);
            emit seekRequested(frac);
            break;
        }
        default:
            break;
    }
}

void SkinnedWindow::mousePressEvent(QMouseEvent *e) {
    if (e->button() != Qt::LeftButton) {
        QWidget::mousePressEvent(e);
        return;
    }
    using namespace coords;
    const QPoint pt = e->position().toPoint();

    if (kMenuBtn.contains(pt.x(), pt.y())) { emit menuClicked(); return; }
    if (kMinimizeBtn.contains(pt.x(), pt.y())) { emit minimizeClicked(); return; }
    if (kShadeBtn.contains(pt.x(), pt.y())) { emit shadeClicked(); return; }
    if (kCloseBtn.contains(pt.x(), pt.y())) { emit closeClicked(); return; }
    if (kEqToggle.contains(pt.x(), pt.y())) { emit eqToggleClicked(); return; }
    if (kPlToggle.contains(pt.x(), pt.y())) { emit plToggleClicked(); return; }

    const int btn = transportButtonAt(pt);
    if (btn >= 0) {
        m_pressedButton = btn;
        update();
        return;
    }

    if (Rect{kVolumeX, kVolumeY, kVolumeW, kVolumeH}.contains(pt.x(), pt.y())) {
        m_drag = Drag::Volume;
        updateSliderFromX(pt.x());
        return;
    }
    if (Rect{kBalanceX, kBalanceY, kBalanceW, kBalanceH}.contains(pt.x(), pt.y())) {
        m_drag = Drag::Balance;
        updateSliderFromX(pt.x());
        return;
    }
    if (Rect{kPosbarX, kPosbarY, kPosbarW, kPosbarH}.contains(pt.x(), pt.y())) {
        m_drag = Drag::Seek;
        updateSliderFromX(pt.x());
        return;
    }

    // Otherwise a click on the titlebar/body drags the frameless window — hand
    // off to the compositor (the Wayland-correct way to move a top-level).
    if (pt.y() < kTitlebarDragH && windowHandle()) {
        windowHandle()->startSystemMove();
        return;
    }
    QWidget::mousePressEvent(e);
}

void SkinnedWindow::mouseMoveEvent(QMouseEvent *e) {
    if (m_drag == Drag::Seek || m_drag == Drag::Volume || m_drag == Drag::Balance)
        updateSliderFromX(e->position().toPoint().x());
    else
        QWidget::mouseMoveEvent(e);
}

void SkinnedWindow::mouseReleaseEvent(QMouseEvent *e) {
    if (e->button() == Qt::LeftButton && m_pressedButton >= 0) {
        if (transportButtonAt(e->position().toPoint()) == m_pressedButton) {
            switch (m_pressedButton) {
                case 0: emit prevClicked(); break;
                case 1: emit playClicked(); break;
                case 2: emit pauseClicked(); break;
                case 3: emit stopClicked(); break;
                case 4: emit nextClicked(); break;
                case 5: emit ejectClicked(); break;
            }
        }
        m_pressedButton = -1;
        update();
    }
    m_drag = Drag::None;
    QWidget::mouseReleaseEvent(e);
}

}  // namespace pyrrha
