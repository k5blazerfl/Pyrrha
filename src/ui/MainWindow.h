// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#pragma once

#include <QMainWindow>

#include "sources/LocalSource.h"

class QLabel;
class QListWidget;
class QPushButton;
class QSlider;

namespace pyrrha {

class Player;
class PlayerEngine;
class MetadataScanner;
class MprisAdapter;
class SkinnedWindow;

// The prototype main window: a playlist plus a transport bar (prev / play-pause /
// next / stop, a seek slider with time labels, and a volume slider). Enough to
// prove the spine — sources feed the queue, the Player drives the engine, the UI
// only ever talks to the Player. The Winamp skin engine grows on top of this.
class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(QWidget *parent = nullptr);

private slots:
    void openFiles();
    void openFolder();
    void reloadQueue();
    void onTrackUpdated(int index, const Track &track);
    void openClassicSkin();   // open a Winamp-skinned window wired to the player

private:
    void buildUi();
    void wireEngine();
    void updatePlayPauseButton();
    void setNowPlaying(int index);
    void addAndScan(int firstNewIndex);   // rebuild list, then probe new items
    static QString rowLabel(const Track &track);

    LocalSource m_source;
    PlayerEngine *m_engine;    // parented to this window
    Player *m_player;          // parented to this window
    MetadataScanner *m_scanner;  // parented to this window
    MprisAdapter *m_mpris;       // desktop media integration (parented to window)
    SkinnedWindow *m_classic = nullptr;  // classic skin UI, created on demand

    QListWidget *m_playlist = nullptr;
    QPushButton *m_playPause = nullptr;
    QSlider *m_seek = nullptr;
    QSlider *m_volume = nullptr;
    QLabel *m_elapsed = nullptr;
    QLabel *m_total = nullptr;
    QLabel *m_nowPlaying = nullptr;

    bool m_seeking = false;   // true while the user drags the seek slider
};

}  // namespace pyrrha
