// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// The classic Winamp 2 playlist window (fixed 275 wide, resizable height),
// rendered from pledit.bmp with pledit.txt colors: the tiled titlebar + side +
// bottom frame, and the track rows ("N. Artist - Title" + right-aligned
// duration). First cut: the frame + rows. Scrollbar drag, the button bar,
// drag-reorder and the miniplayer clock grow on top.
#pragma once

#include <QColor>
#include <QStringList>
#include <QWidget>

#include "skin/Skin.h"
#include "skin/SkinCoords.h"

namespace pyrrha {

class SkinnedPlaylistWindow : public QWidget {
    Q_OBJECT
public:
    explicit SkinnedPlaylistWindow(QWidget *parent = nullptr);

    bool loadSkin(const QString &path);
    bool hasSkin() const { return m_skin.isValid(); }

    void setRows(const QStringList &titles, const QStringList &durations);
    void setCurrentRow(int i);
    int rowCount() const { return int(m_titles.size()); }
    int currentRow() const { return m_current; }

    QSize sizeHint() const override {
        return {coords::pl::kDefaultW, coords::pl::kDefaultH};
    }

signals:
    void closeClicked();

protected:
    void paintEvent(QPaintEvent *) override;

private:
    void parseColors();
    void blitTitlebar(QPainter &p, int w);
    void blitFrame(QPainter &p, int w, int lh);
    void drawRows(QPainter &p, int w, int lh);

    Skin m_skin;
    QStringList m_titles;
    QStringList m_durations;
    int m_current = -1;
    int m_scroll = 0;

    // pledit.txt colours (Winamp defaults: green on black).
    QColor m_cNormal{0, 255, 0};
    QColor m_cCurrent{255, 255, 255};
    QColor m_cBg{0, 0, 0};
    QColor m_cSelBg{0, 0, 128};
};

}  // namespace pyrrha
