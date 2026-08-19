// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include "ui/MainWindow.h"

#include <QAction>
#include <QFileDialog>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QMenuBar>
#include <QPushButton>
#include <QSlider>
#include <QStyle>
#include <QVBoxLayout>
#include <QWidget>

#include "engine/QtMultimediaEngine.h"
#include "player/Player.h"

namespace pyrrha {

namespace {
QString fmtTime(qint64 ms) {
    if (ms < 0)
        ms = 0;
    const qint64 total = ms / 1000;
    return QStringLiteral("%1:%2")
        .arg(total / 60)
        .arg(total % 60, 2, 10, QChar('0'));
}
}  // namespace

MainWindow::MainWindow(QWidget *parent)
    : QMainWindow(parent),
      m_engine(new QtMultimediaEngine(this)),
      m_player(new Player(m_engine, this)) {
    setWindowTitle(QStringLiteral("Pyrrha"));
    resize(560, 480);
    buildUi();
    wireEngine();
    m_player->setVolume(m_volume->value() / 100.0);
}

void MainWindow::buildUi() {
    // -- menu ---------------------------------------------------------------
    QMenu *file = menuBar()->addMenu(QStringLiteral("&File"));
    file->addAction(QStringLiteral("Open &Files…"), QKeySequence::Open, this,
                    &MainWindow::openFiles);
    file->addAction(QStringLiteral("Open F&older…"), this,
                    &MainWindow::openFolder);
    file->addSeparator();
    file->addAction(QStringLiteral("&Quit"), QKeySequence::Quit, this,
                    &QWidget::close);

    // -- playlist -----------------------------------------------------------
    m_playlist = new QListWidget(this);
    connect(m_playlist, &QListWidget::itemActivated, this,
            [this](QListWidgetItem *item) {
                m_player->playIndex(m_playlist->row(item));
            });

    // -- transport ----------------------------------------------------------
    const QStyle *s = style();
    auto *prev = new QPushButton(s->standardIcon(QStyle::SP_MediaSkipBackward), {});
    m_playPause = new QPushButton(s->standardIcon(QStyle::SP_MediaPlay), {});
    auto *next = new QPushButton(s->standardIcon(QStyle::SP_MediaSkipForward), {});
    auto *stop = new QPushButton(s->standardIcon(QStyle::SP_MediaStop), {});
    connect(prev, &QPushButton::clicked, m_player, &Player::previous);
    connect(m_playPause, &QPushButton::clicked, m_player, &Player::togglePlayPause);
    connect(next, &QPushButton::clicked, m_player, &Player::next);
    connect(stop, &QPushButton::clicked, m_player, &Player::stop);

    m_seek = new QSlider(Qt::Horizontal, this);
    m_seek->setRange(0, 0);
    connect(m_seek, &QSlider::sliderPressed, this, [this] { m_seeking = true; });
    connect(m_seek, &QSlider::sliderReleased, this, [this] {
        m_player->seek(m_seek->value());
        m_seeking = false;
    });

    m_elapsed = new QLabel(QStringLiteral("0:00"), this);
    m_total = new QLabel(QStringLiteral("0:00"), this);
    m_nowPlaying = new QLabel(QStringLiteral("Nothing playing"), this);
    m_nowPlaying->setAlignment(Qt::AlignCenter);

    m_volume = new QSlider(Qt::Horizontal, this);
    m_volume->setRange(0, 100);
    m_volume->setValue(80);
    m_volume->setMaximumWidth(120);
    connect(m_volume, &QSlider::valueChanged, this,
            [this](int v) { m_player->setVolume(v / 100.0); });

    auto *seekRow = new QHBoxLayout;
    seekRow->addWidget(m_elapsed);
    seekRow->addWidget(m_seek, 1);
    seekRow->addWidget(m_total);

    auto *controls = new QHBoxLayout;
    controls->addWidget(prev);
    controls->addWidget(m_playPause);
    controls->addWidget(next);
    controls->addWidget(stop);
    controls->addStretch(1);
    controls->addWidget(new QLabel(QStringLiteral("Vol"), this));
    controls->addWidget(m_volume);

    auto *root = new QVBoxLayout;
    root->addWidget(m_playlist, 1);
    root->addWidget(m_nowPlaying);
    root->addLayout(seekRow);
    root->addLayout(controls);

    auto *central = new QWidget(this);
    central->setLayout(root);
    setCentralWidget(central);
}

void MainWindow::wireEngine() {
    connect(m_engine, &PlayerEngine::positionChanged, this, [this](qint64 ms) {
        if (!m_seeking)
            m_seek->setValue(static_cast<int>(ms));
        m_elapsed->setText(fmtTime(ms));
    });
    connect(m_engine, &PlayerEngine::durationChanged, this, [this](qint64 ms) {
        m_seek->setRange(0, static_cast<int>(ms));
        m_total->setText(fmtTime(ms));
    });
    connect(m_engine, &PlayerEngine::stateChanged, this,
            [this](PlayerEngine::State) { updatePlayPauseButton(); });
    connect(m_player, &Player::currentChanged, this, &MainWindow::setNowPlaying);
}

void MainWindow::updatePlayPauseButton() {
    const bool playing = m_engine->state() == PlayerEngine::State::Playing;
    m_playPause->setIcon(style()->standardIcon(playing ? QStyle::SP_MediaPause
                                                       : QStyle::SP_MediaPlay));
}

void MainWindow::setNowPlaying(int index) {
    const Track *t = m_player->current();
    m_nowPlaying->setText(t ? t->displayTitle()
                            : QStringLiteral("Nothing playing"));
    if (index >= 0 && index < m_playlist->count())
        m_playlist->setCurrentRow(index);
    updatePlayPauseButton();
}

void MainWindow::openFiles() {
    QString filter = QStringLiteral("Audio files (");
    for (const QString &ext : LocalSource::audioExtensions())
        filter += QStringLiteral("*.%1 ").arg(ext);
    filter = filter.trimmed() + QStringLiteral(");;All files (*)");
    const QStringList paths = QFileDialog::getOpenFileNames(
        this, QStringLiteral("Open audio files"), {}, filter);
    if (!paths.isEmpty() && m_source.addFiles(paths) > 0)
        reloadQueue();
}

void MainWindow::openFolder() {
    const QString dir = QFileDialog::getExistingDirectory(
        this, QStringLiteral("Open music folder"));
    if (!dir.isEmpty() && m_source.addFolder(dir) > 0)
        reloadQueue();
}

void MainWindow::reloadQueue() {
    const QVector<Track> tracks = m_source.tracks();
    m_player->setQueue(tracks);
    m_playlist->clear();
    for (const Track &t : tracks)
        m_playlist->addItem(t.displayTitle());
}

}  // namespace pyrrha
