// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// The classic Winamp 2 main window (275×116, frameless), rendered entirely from
// a loaded Skin's sprite sheets. First cut: the static face reflecting player
// state (title, time, play/pause, volume, balance). Interaction (buttons, seek,
// drag, windowshade, the visualizer) grows on top of this.
#pragma once

#include <optional>

#include <QString>
#include <QWidget>

#include "skin/BitmapFont.h"
#include "skin/Skin.h"
#include "skin/SkinCoords.h"

namespace pyrrha {

class SkinnedWindow : public QWidget {
    Q_OBJECT
public:
    explicit SkinnedWindow(QWidget *parent = nullptr);

    bool loadSkin(const QString &path);   // .wsz or unpacked dir
    bool hasSkin() const { return m_skin.isValid(); }

    void setTitle(const QString &title);
    void setTimeMs(qint64 ms);
    void setDurationMs(qint64 ms);
    void setPlaying(bool playing);
    void setVolume(qreal v);   // 0..1
    void setBalance(qreal b);  // -1..1

    QSize sizeHint() const override { return {coords::kW, coords::kH}; }

signals:
    // Transport (the six cbuttons.bmp buttons).
    void prevClicked();
    void playClicked();
    void pauseClicked();
    void stopClicked();
    void nextClicked();
    void ejectClicked();
    // Titlebar.
    void menuClicked();
    void minimizeClicked();
    void shadeClicked();
    void closeClicked();
    void eqToggleClicked();   // show/hide the equalizer window
    void plToggleClicked();   // show/hide the playlist window
    // Sliders (user-driven).
    void seekRequested(qreal fraction);   // 0..1 of the track
    void volumeChanged(qreal v);          // 0..1
    void balanceChanged(qreal b);         // -1..1

protected:
    void paintEvent(QPaintEvent *) override;
    void mousePressEvent(QMouseEvent *) override;
    void mouseMoveEvent(QMouseEvent *) override;
    void mouseReleaseEvent(QMouseEvent *) override;

private:
    enum class Drag { None, Window, Seek, Volume, Balance };

    void drawTime(QPainter &p) const;
    int transportButtonAt(const QPoint &pt) const;  // index into kButtons, or -1
    void updateSliderFromX(int x);                    // drives the active drag

    Drag m_drag = Drag::None;
    int m_pressedButton = -1;   // transport button held down, or -1

    Skin m_skin;
    std::optional<TextFont> m_text;
    std::optional<NumberFont> m_num;

    QString m_title = QStringLiteral("PYRRHA");
    qint64 m_timeMs = 0;
    qint64 m_durationMs = 0;
    bool m_playing = false;
    qreal m_volume = 0.8;
    qreal m_balance = 0.0;
};

}  // namespace pyrrha
