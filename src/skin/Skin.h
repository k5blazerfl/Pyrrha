// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// Loader for classic Winamp 2 skins — a .wsz ZIP of BMP sprite sheets (plus a
// few .txt config files and optional .cur cursors), or an unpacked directory of
// the same. A faithful C++/Qt6 port of py-pyrrha's skinned/skin.py. Files are
// keyed by lower-cased basename (Winamp skins are inconsistent about case and
// nesting), sprite sheets decode lazily, and sprite() pads out-of-bounds reads
// with transparency (some skins ship short sheets and the standard rect must be
// a no-op, not a black block).
#pragma once

#include <QByteArray>
#include <QCursor>
#include <QHash>
#include <QImage>
#include <QRegion>
#include <QString>

namespace pyrrha {

class Skin {
public:
    Skin() = default;

    // Load a .wsz/.zip archive or an unpacked skin directory. Returns false if
    // nothing usable was found.
    bool load(const QString &path);
    bool isValid() const { return !m_bmp.isEmpty(); }

    bool has(const QString &name) const;              // is <name> a known sheet
    QString text(const QString &name) const;          // .txt contents, or ""
    QImage image(const QString &name) const;          // full decoded sheet (cached)

    // A w×h sub-rect of sheet <name>. Out-of-bounds area is transparent.
    QImage sprite(const QString &name, int x, int y, int w, int h) const;

    bool hasCursors() const { return !m_cur.isEmpty(); }
    QCursor cursor(const QString &name) const;        // .cur → QCursor, else default

    // A shaped-window mask from region.txt section ("normal", "windowshade",
    // "equalizer", "equalizerws"), scaled. Null region when the skin is
    // rectangular (no region.txt).
    QRegion region(const QString &section, qreal scale = 1.0) const;

private:
    void store(const QString &name, const QByteArray &data);
    QImage decode(const QByteArray &data) const;
    void parseRegions() const;

    // Tolerant BMP fallback for the odd Winamp-era variants Qt's loader rejects.
    static QImage decodeBmp(const QByteArray &data);

    QHash<QString, QByteArray> m_bmp;   // sheet bytes, lower-cased basename
    QHash<QString, QByteArray> m_cur;   // cursor bytes
    QHash<QString, QString> m_txt;      // config files (latin-1)

    mutable QHash<QString, QImage> m_imageCache;
    mutable QHash<QString, QCursor> m_cursorCache;
    mutable QHash<QString, QRegion> m_regionCache;   // key "section@scale"
    mutable QHash<QString, QList<QPolygon>> m_regions;  // parsed region.txt
    mutable bool m_regionsParsed = false;
};

}  // namespace pyrrha
