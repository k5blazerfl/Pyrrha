// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// The classic Winamp 2 equalizer window (275×116), rendered from eqmain.bmp: the
// face plus the preamp + 10 band slider thumbs at their gain positions. First
// cut: static reflection of the EQ curve. Slider drag / ON-AUTO-Presets buttons /
// the response graph grow on top of this.
#pragma once

#include <array>
#include <memory>

#include <QString>
#include <QWidget>

#include "skin/Skin.h"
#include "skin/SkinCoords.h"

namespace pyrrha {

class SkinnedEqWindow : public QWidget {
    Q_OBJECT
public:
    explicit SkinnedEqWindow(QWidget *parent = nullptr);

    bool loadSkin(const QString &path);
    void setSkin(std::shared_ptr<Skin> skin);   // adopt an already-parsed Skin (shared)
    bool hasSkin() const { return m_skin && m_skin->isValid(); }

    void setPreamp(qreal g);                 // -1..1 (0 = flat)
    void setBand(int i, qreal g);            // i in 0..9
    void setBands(const std::array<qreal, coords::eq::kBands> &g);

    QSize sizeHint() const override { return {coords::eq::kW, coords::eq::kH}; }

signals:
    void closeClicked();
    void preampChanged(qreal g);
    void bandChanged(int i, qreal g);

protected:
    void paintEvent(QPaintEvent *) override;

private:
    std::shared_ptr<Skin> m_skin;
    qreal m_preamp = 0.0;
    std::array<qreal, coords::eq::kBands> m_bands{};  // zero-init = flat
};

}  // namespace pyrrha
