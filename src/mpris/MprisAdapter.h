// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include <QDBusAbstractAdaptor>
#include <QDBusObjectPath>
#include <QObject>
#include <QStringList>
#include <QVariantMap>

namespace pyrrha {

class Player;
class MprisAdapter;

// org.mpris.MediaPlayer2 — the root object every MPRIS2 media player exports.
// Lets the desktop identify us and raise/quit the window.
class MprisRoot : public QDBusAbstractAdaptor {
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.mpris.MediaPlayer2")
    Q_PROPERTY(bool CanQuit READ canQuit CONSTANT)
    Q_PROPERTY(bool CanRaise READ canRaise CONSTANT)
    Q_PROPERTY(bool HasTrackList READ hasTrackList CONSTANT)
    Q_PROPERTY(QString Identity READ identity CONSTANT)
    Q_PROPERTY(QString DesktopEntry READ desktopEntry CONSTANT)
    Q_PROPERTY(QStringList SupportedUriSchemes READ supportedUriSchemes CONSTANT)
    Q_PROPERTY(QStringList SupportedMimeTypes READ supportedMimeTypes CONSTANT)
public:
    explicit MprisRoot(MprisAdapter *parent);

    bool canQuit() const { return true; }
    bool canRaise() const { return true; }
    bool hasTrackList() const { return false; }
    QString identity() const { return QStringLiteral("Pyrrha"); }
    QString desktopEntry() const {
        return QStringLiteral("io.github.k5blazerfl.Pyrrha");
    }
    QStringList supportedUriSchemes() const { return {QStringLiteral("file")}; }
    QStringList supportedMimeTypes() const;

public slots:
    void Raise();
    void Quit();

private:
    MprisAdapter *m_adapter;
};

// org.mpris.MediaPlayer2.Player — playback status, metadata and transport.
// This is what the desktop's media keys (Play/Pause/Next/Stop) drive.
class MprisPlayer : public QDBusAbstractAdaptor {
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.mpris.MediaPlayer2.Player")
    Q_PROPERTY(QString PlaybackStatus READ playbackStatus)
    Q_PROPERTY(QVariantMap Metadata READ metadata)
    Q_PROPERTY(double Volume READ volume WRITE setVolume)
    Q_PROPERTY(qlonglong Position READ position)
    Q_PROPERTY(double Rate READ rate WRITE setRate)
    Q_PROPERTY(double MinimumRate READ minimumRate CONSTANT)
    Q_PROPERTY(double MaximumRate READ maximumRate CONSTANT)
    Q_PROPERTY(bool CanGoNext READ canGoNext)
    Q_PROPERTY(bool CanGoPrevious READ canGoPrevious)
    Q_PROPERTY(bool CanPlay READ canPlay)
    Q_PROPERTY(bool CanPause READ canPause)
    Q_PROPERTY(bool CanSeek READ canSeek)
    Q_PROPERTY(bool CanControl READ canControl CONSTANT)
public:
    explicit MprisPlayer(MprisAdapter *parent);

    QString playbackStatus() const;   // "Playing" | "Paused" | "Stopped"
    QVariantMap metadata() const;     // the MPRIS a{sv} metadata map
    double volume() const;
    void setVolume(double v);
    qlonglong position() const;       // microseconds
    double rate() const { return 1.0; }
    void setRate(double) {}
    double minimumRate() const { return 1.0; }
    double maximumRate() const { return 1.0; }
    bool canGoNext() const;
    bool canGoPrevious() const;
    bool canPlay() const;
    bool canPause() const;
    bool canSeek() const { return true; }
    bool canControl() const { return true; }

public slots:
    void PlayPause();
    void Play();
    void Pause();
    void Stop();
    void Next();
    void Previous();
    void Seek(qlonglong offsetUs);
    void SetPosition(const QDBusObjectPath &trackId, qlonglong posUs);

signals:
    void Seeked(qlonglong positionUs);

private:
    Player *player() const;
    MprisAdapter *m_adapter;
};

// Host object registered at /org/mpris/MediaPlayer2. Owns the two adaptors,
// claims the well-known name org.mpris.MediaPlayer2.pyrrha, and pushes
// PropertiesChanged as the Player's state moves. QtDBus only — no GLib.
class MprisAdapter : public QObject {
    Q_OBJECT
public:
    explicit MprisAdapter(Player *player, QObject *parent = nullptr);

    // Register on the session bus. Returns false (harmlessly) when there is no
    // session bus — the app runs fine without desktop media integration.
    bool registerOnBus();

    Player *player() const { return m_player; }

    void requestRaise() { emit raiseRequested(); }
    void requestQuit() { emit quitRequested(); }

signals:
    void raiseRequested();
    void quitRequested();

private slots:
    void onCurrentChanged();
    void onStateChanged();
    void onVolumeChanged();
    void onSeeked(qint64 ms);

private:
    friend class MprisRoot;
    friend class MprisPlayer;
    void pushChanged(const QString &iface, const QStringList &props);

    Player *m_player;
    MprisRoot *m_root;
    MprisPlayer *m_playerIface;
};

}  // namespace pyrrha
