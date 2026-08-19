// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// The two classic Winamp bitmap fonts: the 5×6 TEXT.BMP font (song title,
// bitrate/khz) and the 9×13 NUMBERS.BMP / NUMS_EX.BMP digits (the clock). A port
// of py-pyrrha's skinned/font.py.
#pragma once

#include <QChar>
#include <QHash>
#include <QImage>
#include <QPoint>
#include <QString>

namespace pyrrha {

class Skin;

// 5×6 character font from text.bmp. Uppercase only (Winamp uppercases titles).
class TextFont {
public:
    static constexpr int CharW = 5;
    static constexpr int CharH = 6;

    explicit TextFont(const Skin *skin);
    QImage render(const QString &text) const;  // ARGB, len*5 × 6

private:
    const Skin *m_skin;
    QHash<QChar, QPoint> m_map;   // char → (x,y) in text.bmp
};

// 9×13 digit font from numbers.bmp (or the extended nums_ex.bmp with a real "-").
class NumberFont {
public:
    static constexpr int NumW = 9;
    static constexpr int NumH = 13;

    explicit NumberFont(const Skin *skin);
    QImage digit(QChar ch) const;   // '0'..'9', '-', or blank for anything else

private:
    QImage syntheticMinus() const;

    const Skin *m_skin;
    QString m_bmp;
    int m_cells;
    mutable QImage m_minusCache;
};

}  // namespace pyrrha
