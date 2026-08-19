// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "skin/Skin.h"

#include <functional>

#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QPainter>
#include <QPixmap>
#include <QRegularExpression>

#include <KArchiveDirectory>
#include <KArchiveFile>
#include <KZip>

namespace pyrrha {

namespace {
// Parse a tolerant comma/semicolon/space separated int list (region.txt values).
QList<int> parseInts(const QString &s) {
    static const QRegularExpression sep(QStringLiteral("[,;\\s]+"));
    QList<int> out;
    for (const QString &tok : s.split(sep, Qt::SkipEmptyParts)) {
        bool ok = false;
        const double v = tok.toDouble(&ok);  // int(float(tok)) like the Python
        if (ok)
            out.append(static_cast<int>(v));
    }
    return out;
}
}  // namespace

bool Skin::load(const QString &path) {
    m_bmp.clear();
    m_cur.clear();
    m_txt.clear();
    m_imageCache.clear();
    m_cursorCache.clear();
    m_regionCache.clear();
    m_regions.clear();
    m_regionsParsed = false;

    const QFileInfo fi(path);
    if (fi.isDir()) {
        QDirIterator it(path, QDir::Files, QDirIterator::Subdirectories);
        while (it.hasNext()) {
            const QString f = it.next();
            QFile file(f);
            if (file.open(QIODevice::ReadOnly))
                store(f, file.readAll());
        }
    } else {
        KZip zip(path);
        if (!zip.open(QIODevice::ReadOnly))
            return false;
        std::function<void(const KArchiveDirectory *)> walk =
            [&](const KArchiveDirectory *dir) {
                for (const QString &name : dir->entries()) {
                    const KArchiveEntry *e = dir->entry(name);
                    if (!e)
                        continue;
                    if (e->isDirectory())
                        walk(static_cast<const KArchiveDirectory *>(e));
                    else
                        store(name, static_cast<const KArchiveFile *>(e)->data());
                }
            };
        walk(zip.directory());
    }
    return isValid();
}

void Skin::store(const QString &name, const QByteArray &data) {
    const QString base = QFileInfo(name).fileName().toLower();  // basename, lower
    if (base.endsWith(QLatin1String(".bmp")))
        m_bmp.insert(base, data);
    else if (base.endsWith(QLatin1String(".cur")))
        m_cur.insert(base, data);
    else if (base.endsWith(QLatin1String(".txt")))
        m_txt.insert(base, QString::fromLatin1(data));  // config files aren't UTF-8
}

bool Skin::has(const QString &name) const {
    return m_bmp.contains(name.toLower());
}

QString Skin::text(const QString &name) const {
    return m_txt.value(name.toLower());
}

QImage Skin::image(const QString &name) const {
    const QString key = name.toLower();
    const auto cached = m_imageCache.constFind(key);
    if (cached != m_imageCache.constEnd())
        return cached.value();
    QImage img;
    const auto raw = m_bmp.constFind(key);
    if (raw != m_bmp.constEnd())
        img = decode(raw.value());
    m_imageCache.insert(key, img);
    return img;
}

QImage Skin::sprite(const QString &name, int x, int y, int w, int h) const {
    if (w <= 0 || h <= 0)
        return {};
    const QImage img = image(name);
    if (img.isNull()) {
        QImage empty(w, h, QImage::Format_ARGB32_Premultiplied);
        empty.fill(Qt::transparent);
        return empty;
    }
    if (x >= 0 && y >= 0 && x + w <= img.width() && y + h <= img.height())
        return img.copy(x, y, w, h);  // fully in-bounds — cheap

    // Partial: transparent canvas + the in-bounds overlap at its offset (some
    // skins ship short sheets; the padded area must be transparent, not black).
    QImage out(w, h, QImage::Format_ARGB32_Premultiplied);
    out.fill(Qt::transparent);
    const QRect inter = QRect(x, y, w, h) & QRect(0, 0, img.width(), img.height());
    if (!inter.isEmpty()) {
        QPainter p(&out);
        p.drawImage(QPoint(inter.x() - x, inter.y() - y), img, inter);
    }
    return out;
}

QImage Skin::decode(const QByteArray &data) const {
    QImage img;
    if (img.loadFromData(data))            // sniff (also PNG/GIF saved as .bmp)
        return img;
    if (img.loadFromData(data, "BMP"))     // Qt's BMP reader
        return img;
    return decodeBmp(data);                // our tolerant fallback
}

QImage Skin::decodeBmp(const QByteArray &d) {
    if (d.size() < 54 || d[0] != 'B' || d[1] != 'M')
        return {};
    auto u16 = [&](int o) {
        return quint16(quint8(d[o]) | (quint8(d[o + 1]) << 8));
    };
    auto u32 = [&](int o) {
        return quint32(quint8(d[o]) | (quint8(d[o + 1]) << 8) |
                       (quint8(d[o + 2]) << 16) | (quint32(quint8(d[o + 3])) << 24));
    };
    const quint32 offBits = u32(10);
    const quint32 hdr = u32(14);
    const int width = int(u32(18));
    int height = int(u32(22));
    const int bpp = u16(28);
    const quint32 comp = u32(30);
    if (comp != 0 || width <= 0 || width > 20000)
        return {};                          // uncompressed BI_RGB only
    bool topDown = false;
    if (height < 0) {
        height = -height;
        topDown = true;
    }
    if (height <= 0 || height > 20000)
        return {};

    QVector<QRgb> pal;
    if (bpp <= 8) {
        const quint32 clrUsed = u32(46);
        const int entries = clrUsed ? int(clrUsed) : (1 << bpp);
        const int palOff = 14 + int(hdr);
        pal.resize(entries);
        for (int i = 0; i < entries; ++i) {
            const int p = palOff + i * 4;
            pal[i] = (p + 2 < d.size())
                         ? qRgb(quint8(d[p + 2]), quint8(d[p + 1]), quint8(d[p]))
                         : qRgb(0, 0, 0);
        }
    }

    QImage out(width, height, QImage::Format_ARGB32);
    out.fill(Qt::transparent);
    const int rowBytes = ((width * bpp + 31) / 32) * 4;  // 4-byte aligned rows
    for (int row = 0; row < height; ++row) {
        const int srcRow = topDown ? row : (height - 1 - row);
        const int base = int(offBits) + srcRow * rowBytes;
        QRgb *line = reinterpret_cast<QRgb *>(out.scanLine(row));
        for (int x = 0; x < width; ++x) {
            if (bpp == 24) {
                const int p = base + x * 3;
                if (p + 2 < d.size())
                    line[x] = qRgb(quint8(d[p + 2]), quint8(d[p + 1]), quint8(d[p]));
            } else if (bpp == 32) {
                const int p = base + x * 4;
                if (p + 2 < d.size())
                    line[x] = qRgb(quint8(d[p + 2]), quint8(d[p + 1]), quint8(d[p]));
            } else if (bpp == 8) {
                const int p = base + x;
                const int idx = (p < d.size()) ? quint8(d[p]) : 0;
                line[x] = (idx < pal.size()) ? pal[idx] : qRgb(0, 0, 0);
            } else if (bpp == 4) {
                const int p = base + x / 2;
                const quint8 byte = (p < d.size()) ? quint8(d[p]) : 0;
                const int idx = (x & 1) ? (byte & 0x0f) : (byte >> 4);
                line[x] = (idx < pal.size()) ? pal[idx] : qRgb(0, 0, 0);
            }
        }
    }
    return out;
}

QCursor Skin::cursor(const QString &name) const {
    const QString key = name.toLower();
    const auto cached = m_cursorCache.constFind(key);
    if (cached != m_cursorCache.constEnd())
        return cached.value();
    QCursor result;  // default arrow
    const auto raw = m_cur.constFind(key);
    if (raw != m_cur.constEnd()) {
        QByteArray data = raw.value();
        if (data.size() > 14) {
            const quint16 hx = quint8(data[10]) | (quint8(data[11]) << 8);
            const quint16 hy = quint8(data[12]) | (quint8(data[13]) << 8);
            data[2] = 1;  // .cur (type 2) → .ico (type 1) so Qt's ICO reader takes it
            data[3] = 0;
            QImage img;
            if (img.loadFromData(data, "ICO"))
                result = QCursor(QPixmap::fromImage(img), hx, hy);
        }
    }
    m_cursorCache.insert(key, result);
    return result;
}

void Skin::parseRegions() const {
    m_regionsParsed = true;
    const QString txt = text(QStringLiteral("region.txt"));
    if (txt.isEmpty())
        return;

    QString section, numPoints, pointList, curKey;
    auto flush = [&]() {
        if (section.isEmpty())
            return;
        const QList<int> counts = parseInts(numPoints);
        const QList<int> pts = parseInts(pointList);
        QList<QPolygon> polys;
        int idx = 0;
        for (int n : counts) {
            QPolygon poly;
            for (int i = 0; i < n; ++i) {
                if (idx + 1 < pts.size()) {
                    poly << QPoint(pts[idx], pts[idx + 1]);
                    idx += 2;
                }
            }
            if (poly.size() >= 3)
                polys << poly;
        }
        if (!polys.isEmpty())
            m_regions.insert(section, polys);
        numPoints.clear();
        pointList.clear();
        curKey.clear();
    };

    for (QString line : txt.split(QLatin1Char('\n'))) {
        line = line.trimmed();
        if (line.isEmpty())
            continue;
        if (line.startsWith(QLatin1Char('[')) && line.endsWith(QLatin1Char(']'))) {
            flush();
            section = line.mid(1, line.size() - 2).toLower();
        } else if (line.contains(QLatin1Char('='))) {
            const QString k = line.section('=', 0, 0).trimmed().toLower();
            const QString v = line.section('=', 1);
            if (k.startsWith(QLatin1String("numpoints"))) {
                curKey = QStringLiteral("n");
                numPoints += QLatin1Char(',') + v;
            } else if (k.startsWith(QLatin1String("pointlist"))) {
                curKey = QStringLiteral("p");
                pointList += QLatin1Char(',') + v;
            } else {
                curKey.clear();
            }
        } else if (curKey == QLatin1String("n")) {
            numPoints += QLatin1Char(',') + line;   // continuation
        } else if (curKey == QLatin1String("p")) {
            pointList += QLatin1Char(',') + line;
        }
    }
    flush();
}

QRegion Skin::region(const QString &section, qreal scale) const {
    if (!m_regionsParsed)
        parseRegions();
    const QString key =
        QStringLiteral("%1@%2").arg(section.toLower()).arg(scale, 0, 'f', 3);
    const auto cached = m_regionCache.constFind(key);
    if (cached != m_regionCache.constEnd())
        return cached.value();
    QRegion reg;
    const auto it = m_regions.constFind(section.toLower());
    if (it != m_regions.constEnd()) {
        for (QPolygon poly : it.value()) {
            if (scale != 1.0) {
                QPolygon scaled;
                for (const QPoint &p : poly)
                    scaled << QPoint(qRound(p.x() * scale), qRound(p.y() * scale));
                poly = scaled;
            }
            reg = reg.united(QRegion(poly));
        }
    }
    m_regionCache.insert(key, reg);
    return reg;
}

}  // namespace pyrrha
