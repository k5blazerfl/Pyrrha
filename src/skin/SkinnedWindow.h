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

protected:
    void paintEvent(QPaintEvent *) override;

private:
    void drawTime(QPainter &p) const;

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
