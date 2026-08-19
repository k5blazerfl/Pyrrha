// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "sources/MetadataScanner.h"

#include <QFile>

#include <taglib/audioproperties.h>
#include <taglib/fileref.h>
#include <taglib/tag.h>

namespace pyrrha {

namespace {
QString toQString(const TagLib::String &s) {
    return QString::fromUtf8(s.toCString(true));  // true = UTF-8
}
}  // namespace

MetadataScanner::MetadataScanner(QObject *parent) : QObject(parent) {}

Track MetadataScanner::readTags(const Track &in) {
    Track t = in;
    if (!t.url.isLocalFile())
        return t;  // TagLib reads files; streams keep their source-provided info

    const QByteArray path = QFile::encodeName(t.url.toLocalFile());
    const TagLib::FileRef file(path.constData());
    if (file.isNull())
        return t;

    if (const TagLib::Tag *tag = file.tag()) {
        const QString title = toQString(tag->title()).trimmed();
        const QString artist = toQString(tag->artist()).trimmed();
        const QString album = toQString(tag->album()).trimmed();
        if (!title.isEmpty())
            t.title = title;
        if (!artist.isEmpty())
            t.artist = artist;
        if (!album.isEmpty())
            t.album = album;
    }
    if (const TagLib::AudioProperties *props = file.audioProperties()) {
        const int ms = props->lengthInMilliseconds();
        if (ms > 0)
            t.durationMs = ms;
    }
    return t;
}

void MetadataScanner::scan(const QVector<Track> &tracks, int baseIndex) {
    // Synchronous: TagLib reads are fast (no decode, no I/O beyond the header).
    // If a very large library ever makes this block noticeably, the read loop can
    // move to a worker thread behind these same signals.
    for (int i = 0; i < tracks.size(); ++i)
        emit trackUpdated(baseIndex + i, readTags(tracks[i]));
    emit finished();
}

}  // namespace pyrrha
