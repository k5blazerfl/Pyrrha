// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "mpris/MprisAdapter.h"

#include <QDBusConnection>
#include <QDBusMessage>

#include "engine/PlayerEngine.h"
#include "player/Player.h"

namespace pyrrha {

namespace {
constexpr auto kObjectPath = "/org/mpris/MediaPlayer2";
constexpr auto kServiceName = "org.mpris.MediaPlayer2.pyrrha";
constexpr auto kPlayerIface = "org.mpris.MediaPlayer2.Player";

QString statusString(PlayerEngine::State s) {
    switch (s) {
        case PlayerEngine::State::Playing: return QStringLiteral("Playing");
        case PlayerEngine::State::Paused:  return QStringLiteral("Paused");
        case PlayerEngine::State::Stopped: return QStringLiteral("Stopped");
    }
    return QStringLiteral("Stopped");
}
}  // namespace

// -- MprisRoot --------------------------------------------------------------

MprisRoot::MprisRoot(MprisAdapter *parent)
    : QDBusAbstractAdaptor(parent), m_adapter(parent) {}

QStringList MprisRoot::supportedMimeTypes() const {
    return {QStringLiteral("audio/mpeg"),  QStringLiteral("audio/flac"),
            QStringLiteral("audio/ogg"),   QStringLiteral("audio/x-vorbis+ogg"),
            QStringLiteral("audio/mp4"),   QStringLiteral("audio/x-wav")};
}

void MprisRoot::Raise() { m_adapter->requestRaise(); }
void MprisRoot::Quit() { m_adapter->requestQuit(); }

// -- MprisPlayer ------------------------------------------------------------

MprisPlayer::MprisPlayer(MprisAdapter *parent)
    : QDBusAbstractAdaptor(parent), m_adapter(parent) {}

Player *MprisPlayer::player() const { return m_adapter->player(); }

QString MprisPlayer::playbackStatus() const {
    return statusString(player()->engine()->state());
}

QVariantMap MprisPlayer::metadata() const {
    QVariantMap m;
    const Track *t = player()->current();
    if (!t) {
        // No current track — a valid empty-ish map with the "no track" path.
        m.insert(QStringLiteral("mpris:trackid"),
                 QVariant::fromValue(QDBusObjectPath(
                     "/org/mpris/MediaPlayer2/TrackList/NoTrack")));
        return m;
    }
    const QString path =
        QStringLiteral("/io/github/k5blazerfl/Pyrrha/track/%1")
            .arg(player()->currentIndex());
    m.insert(QStringLiteral("mpris:trackid"),
             QVariant::fromValue(QDBusObjectPath(path)));
    if (t->durationMs > 0)
        m.insert(QStringLiteral("mpris:length"),
                 static_cast<qlonglong>(t->durationMs) * 1000);  // µs
    if (!t->title.isEmpty())
        m.insert(QStringLiteral("xesam:title"), t->title);
    if (!t->artist.isEmpty())
        m.insert(QStringLiteral("xesam:artist"), QStringList{t->artist});
    if (!t->album.isEmpty())
        m.insert(QStringLiteral("xesam:album"), t->album);
    if (t->url.isValid())
        m.insert(QStringLiteral("xesam:url"), t->url.toString());
    return m;
}

double MprisPlayer::volume() const { return player()->volume(); }
void MprisPlayer::setVolume(double v) {
    player()->setVolume(qBound(0.0, v, 1.0));
}

qlonglong MprisPlayer::position() const {
    return static_cast<qlonglong>(player()->engine()->position()) * 1000;  // µs
}

bool MprisPlayer::canGoNext() const {
    const Player *p = player();
    return !p->queue().isEmpty() && p->currentIndex() < p->queue().size() - 1;
}
bool MprisPlayer::canGoPrevious() const {
    return player()->currentIndex() > 0;
}
bool MprisPlayer::canPlay() const { return !player()->queue().isEmpty(); }
bool MprisPlayer::canPause() const {
    return player()->engine()->state() == PlayerEngine::State::Playing;
}

void MprisPlayer::PlayPause() { player()->togglePlayPause(); }
void MprisPlayer::Play() {
    if (player()->engine()->state() != PlayerEngine::State::Playing)
        player()->togglePlayPause();
}
void MprisPlayer::Pause() {
    if (player()->engine()->state() == PlayerEngine::State::Playing)
        player()->togglePlayPause();
}
void MprisPlayer::Stop() { player()->stop(); }
void MprisPlayer::Next() { player()->next(); }
void MprisPlayer::Previous() { player()->previous(); }

void MprisPlayer::Seek(qlonglong offsetUs) {
    const qint64 target = player()->engine()->position() + offsetUs / 1000;
    player()->seek(target < 0 ? 0 : target);
}
void MprisPlayer::SetPosition(const QDBusObjectPath &, qlonglong posUs) {
    player()->seek(posUs / 1000);
}

// -- MprisAdapter -----------------------------------------------------------

MprisAdapter::MprisAdapter(Player *player, QObject *parent)
    : QObject(parent), m_player(player), m_root(new MprisRoot(this)),
      m_playerIface(new MprisPlayer(this)) {
    connect(m_player, &Player::currentChanged, this,
            &MprisAdapter::onCurrentChanged);
    connect(m_player->engine(), &PlayerEngine::stateChanged, this,
            &MprisAdapter::onStateChanged);
    connect(m_player, &Player::volumeChanged, this,
            &MprisAdapter::onVolumeChanged);
    connect(m_player, &Player::seeked, this, &MprisAdapter::onSeeked);
}

bool MprisAdapter::registerOnBus() {
    QDBusConnection bus = QDBusConnection::sessionBus();
    if (!bus.isConnected())
        return false;
    if (!bus.registerObject(QString::fromLatin1(kObjectPath), this,
                            QDBusConnection::ExportAdaptors))
        return false;
    return bus.registerService(QString::fromLatin1(kServiceName));
}

void MprisAdapter::pushChanged(const QString &iface, const QStringList &props) {
    QVariantMap changed;
    for (const QString &p : props)
        changed.insert(p, m_playerIface->property(p.toLatin1().constData()));
    QDBusMessage sig = QDBusMessage::createSignal(
        QString::fromLatin1(kObjectPath),
        QStringLiteral("org.freedesktop.DBus.Properties"),
        QStringLiteral("PropertiesChanged"));
    sig << iface << changed << QStringList();
    QDBusConnection::sessionBus().send(sig);
}

void MprisAdapter::onCurrentChanged() {
    pushChanged(QString::fromLatin1(kPlayerIface),
                {QStringLiteral("Metadata"), QStringLiteral("PlaybackStatus"),
                 QStringLiteral("CanGoNext"), QStringLiteral("CanGoPrevious"),
                 QStringLiteral("CanPlay"), QStringLiteral("CanPause")});
}

void MprisAdapter::onStateChanged() {
    pushChanged(QString::fromLatin1(kPlayerIface),
                {QStringLiteral("PlaybackStatus"), QStringLiteral("CanPause")});
}

void MprisAdapter::onVolumeChanged() {
    pushChanged(QString::fromLatin1(kPlayerIface), {QStringLiteral("Volume")});
}

void MprisAdapter::onSeeked(qint64 ms) {
    emit m_playerIface->Seeked(static_cast<qlonglong>(ms) * 1000);
}

}  // namespace pyrrha
