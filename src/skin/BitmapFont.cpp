// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "skin/BitmapFont.h"

#include <QColor>
#include <QPainter>

#include "skin/Skin.h"

namespace pyrrha {

// The classic text.bmp layout (font.py _ROWS). Non-ASCII via \u escapes so the
// source encoding can't corrupt the glyph positions.
static const QStringList kTextRows = {
    QStringLiteral("ABCDEFGHIJKLMNOPQRSTUVWXYZ\"@ "),
    QString::fromUtf8("0123456789….:()-'!_+\\/[]^&%.=$#"),
    QString::fromUtf8("ÅÖÄ?* "),  // Å Ö Ä ? *
};

TextFont::TextFont(const Skin *skin) : m_skin(skin) {
    for (int row = 0; row < kTextRows.size(); ++row) {
        const QString &chars = kTextRows[row];
        for (int col = 0; col < chars.size(); ++col) {
            const QChar ch = chars[col];
            if (!m_map.contains(ch))  // setdefault — first occurrence wins
                m_map.insert(ch, QPoint(col * CharW, row * CharH));
        }
    }
}

QImage TextFont::render(const QString &text) const {
    const int width = qMax(1, int(text.size()) * CharW);
    QImage img(width, CharH, QImage::Format_ARGB32_Premultiplied);
    img.fill(Qt::transparent);
    QPainter p(&img);
    for (int i = 0; i < text.size(); ++i) {
        const QChar ch = text[i];
        if (ch == QLatin1Char(' '))
            continue;  // blank cell isn't reliably empty across skins
        const auto it = m_map.constFind(ch.toUpper());
        if (it == m_map.constEnd())
            continue;
        p.drawImage(i * CharW, 0,
                    m_skin->sprite(QStringLiteral("text.bmp"), it.value().x(),
                                   it.value().y(), CharW, CharH));
    }
    return img;
}

NumberFont::NumberFont(const Skin *skin) : m_skin(skin) {
    m_bmp = skin->has(QStringLiteral("numbers.bmp"))
                ? QStringLiteral("numbers.bmp")
                : QStringLiteral("nums_ex.bmp");
    const QImage sheet = skin->image(m_bmp);
    m_cells = sheet.isNull() ? 11 : (sheet.width() / NumW);
}

QImage NumberFont::digit(QChar ch) const {
    int idx;
    if (ch.isDigit()) {
        idx = ch.digitValue();
    } else if (ch == QLatin1Char('-')) {
        if (m_cells >= 12)
            idx = 11;                 // extended sheet ships a real minus
        else
            return syntheticMinus();  // plain numbers.bmp lacks one
    } else {
        idx = 10;                     // blank cell (spaces / colon gaps)
    }
    return m_skin->sprite(m_bmp, idx * NumW, 0, NumW, NumH);
}

QImage NumberFont::syntheticMinus() const {
    if (!m_minusCache.isNull())
        return m_minusCache;
    QImage img = m_skin->sprite(m_bmp, 10 * NumW, 0, NumW, NumH)
                     .convertToFormat(QImage::Format_ARGB32);
    const QImage sheet = m_skin->image(m_bmp);
    QColor color(210, 210, 210);
    int best = -1;
    if (!sheet.isNull()) {
        const int maxX = qMin(sheet.width(), 10 * NumW);
        for (int x = 0; x < maxX; ++x) {
            for (int y = 0; y < sheet.height(); ++y) {
                const QColor c = sheet.pixelColor(x, y);
                if (c.lightness() > best) {
                    best = c.lightness();
                    color = c;
                }
            }
        }
    }
    QPainter p(&img);
    const int barW = 5;
    p.fillRect((NumW - barW) / 2, NumH / 2, barW, 1, color);
    p.end();
    m_minusCache = img;
    return m_minusCache;
}

}  // namespace pyrrha
