# Pyrrha

[![License: GPL v2+](https://img.shields.io/badge/License-GPLv2+-blue.svg)](LICENSE)

A HeDE-native, skinnable music player — built from the ground up in C++/Qt6, the
same stack as the [HeDE](https://github.com/k5blazerfl/HeDE) shell.

Pyrrha is the survivor who rode out the flood and began the world anew — a fitting
namesake for a player rebuilt from the waterline. This is the ground-up rewrite;
the original PyGObject/Pithos-derived build lives on as
[`py-pyrrha`](https://github.com/k5blazerfl/py-pyrrha).

## Design

- **Native C++20 / Qt6 (Widgets + Multimedia)** — no Python, no PySide; a normal
  Gentoo/Qt app that fits a native desktop and ISO without dragging a runtime in.
- **`PlayerEngine`** abstracts the audio backend. The default is `Qt6::Multimedia`
  (`QMediaPlayer`); a GStreamer engine can be dropped in later for gapless
  playback, ReplayGain and a graphic EQ without touching the rest of the app.
- **`SourceProvider`** abstracts where music comes from. Local files ship in the
  core; internet radio and **Pandora** arrive as sources — Pandora as a *separate*
  GPLv3 plugin, so this GPL-2.0-or-later core never derives from Pithos.
- A Winamp-faithful skin engine is planned on top of this spine.

## Build

```sh
cmake -S . -B build
cmake --build build -j
./build/pyrrha
```

Requires Qt6 Widgets + Multimedia and TagLib
(`dev-qt/qtbase[widgets]`, `dev-qt/qtmultimedia`, `media-libs/taglib`).

## License

GPL-2.0-or-later. Pyrrha is original work with no Pithos ancestry; Pandora support
is kept in a separate GPLv3 plugin so the core stays cleanly GPLv2-or-later.
