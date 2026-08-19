// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "sources/MetadataScanner.h"

#include <QMediaMetaData>
#include <QMediaPlayer>
#include <QTimer>

namespace pyrrha {

namespace {
// How long to wait after a file loads for its string tags to arrive. The FFmpeg
// backend reports duration at LoadedMedia but emits title/artist/album via a
// later metaDataChanged; we finalize as soon as a title shows up, and fall back
// to this timeout for files that simply have no tags.
constexpr int kSettleMs = 400;

bool isLoaded(QMediaPlayer::MediaStatus s) {
    return s == QMediaPlayer::LoadedMedia || s == QMediaPlayer::BufferedMedia;
}
}  // namespace

MetadataScanner::MetadataScanner(QObject *parent)
    : QObject(parent),
      m_player(new QMediaPlayer(this)),
      m_settle(new QTimer(this)) {
    // No audio output is attached and we never call play(), so probing is
    // silent — we only load each source to read its metadata.
    m_settle->setSingleShot(true);
    m_settle->setInterval(kSettleMs);
    connect(m_settle, &QTimer::timeout, this, [this] {
        if (m_awaiting)
            finishCurrent(true);  // grace period elapsed — take what we have
    });

    connect(m_player, &QMediaPlayer::mediaStatusChanged, this,
            [this](QMediaPlayer::MediaStatus status) {
                if (!m_awaiting)
                    return;
                if (status == QMediaPlayer::InvalidMedia)
                    finishCurrent(false);  // skip unreadable files
                else if (isLoaded(status))
                    tryFinalize();
            });
    connect(m_player, &QMediaPlayer::metaDataChanged, this, [this] {
        if (m_awaiting)
            tryFinalize();
    });
    connect(m_player, &QMediaPlayer::errorOccurred, this,
            [this](QMediaPlayer::Error, const QString &) {
                if (m_awaiting)
                    finishCurrent(false);
            });
}

MetadataScanner::~MetadataScanner() = default;

void MetadataScanner::scan(const QVector<Track> &tracks, int baseIndex) {
    for (int i = 0; i < tracks.size(); ++i)
        m_pending.enqueue({baseIndex + i, tracks[i]});
    if (!m_busy)
        probeNext();
}

void MetadataScanner::probeNext() {
    if (m_pending.isEmpty()) {
        m_busy = false;
        m_awaiting = false;
        m_player->setSource(QUrl());  // release the last file
        emit finished();
        return;
    }
    m_busy = true;
    m_awaiting = true;
    m_player->setSource(m_pending.head().track.url);
}

void MetadataScanner::tryFinalize() {
    if (!isLoaded(m_player->mediaStatus()))
        return;  // metadata may arrive before the media reports loaded
    const QString title =
        m_player->metaData().stringValue(QMediaMetaData::Title).trimmed();
    if (!title.isEmpty())
        finishCurrent(true);           // tags are in — done immediately
    else if (!m_settle->isActive())
        m_settle->start();             // wait briefly for late (or absent) tags
}

void MetadataScanner::finishCurrent(bool readMeta) {
    m_settle->stop();
    if (m_pending.isEmpty()) {
        m_awaiting = false;
        return;
    }
    m_awaiting = false;
    const Pending item = m_pending.dequeue();
    if (readMeta) {
        Track enriched = item.track;
        applyMetaData(enriched, m_player->metaData(), m_player->duration());
        emit trackUpdated(item.index, enriched);
    }
    probeNext();
}

void MetadataScanner::applyMetaData(Track &track, const QMediaMetaData &md,
                                    qint64 durationMs) {
    const QString title = md.stringValue(QMediaMetaData::Title).trimmed();
    QString artist = md.stringValue(QMediaMetaData::ContributingArtist).trimmed();
    if (artist.isEmpty())
        artist = md.stringValue(QMediaMetaData::AlbumArtist).trimmed();
    if (artist.isEmpty())
        artist = md.stringValue(QMediaMetaData::Author).trimmed();
    const QString album = md.stringValue(QMediaMetaData::AlbumTitle).trimmed();

    if (!title.isEmpty())
        track.title = title;
    if (!artist.isEmpty())
        track.artist = artist;
    if (!album.isEmpty())
        track.album = album;
    if (durationMs > 0)
        track.durationMs = durationMs;
}

}  // namespace pyrrha
