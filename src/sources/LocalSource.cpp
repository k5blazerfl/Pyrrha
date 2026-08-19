// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "sources/LocalSource.h"

#include <QDirIterator>
#include <QFileInfo>

namespace pyrrha {

const QStringList &LocalSource::audioExtensions() {
    static const QStringList kExt = {
        QStringLiteral("mp3"),  QStringLiteral("flac"), QStringLiteral("ogg"),
        QStringLiteral("oga"),  QStringLiteral("opus"), QStringLiteral("m4a"),
        QStringLiteral("aac"),  QStringLiteral("wav"),  QStringLiteral("wv"),
        QStringLiteral("aiff"), QStringLiteral("ape"),  QStringLiteral("wma"),
    };
    return kExt;
}

Track LocalSource::makeTrack(const QString &path) const {
    const QFileInfo info(path);
    Track t;
    t.url = QUrl::fromLocalFile(info.absoluteFilePath());
    t.title = info.completeBaseName();   // filename sans extension, for now
    t.sourceId = id();
    return t;
}

int LocalSource::addFiles(const QStringList &paths) {
    int added = 0;
    for (const QString &path : paths) {
        const QFileInfo info(path);
        if (!info.isFile())
            continue;
        if (!audioExtensions().contains(info.suffix().toLower()))
            continue;
        m_tracks.push_back(makeTrack(path));
        ++added;
    }
    return added;
}

int LocalSource::addFolder(const QString &dir) {
    int added = 0;
    QDirIterator it(dir, QDir::Files, QDirIterator::Subdirectories);
    while (it.hasNext()) {
        const QString path = it.next();
        if (!audioExtensions().contains(QFileInfo(path).suffix().toLower()))
            continue;
        m_tracks.push_back(makeTrack(path));
        ++added;
    }
    return added;
}

}  // namespace pyrrha
