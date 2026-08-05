# Pyrrha

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

A Qt (PySide6) Pandora Radio client — a port of [Pithos](https://pithos.github.io) from GTK to Qt.

Pyrrha keeps Pithos' battle-tested internals (the Pandora API client, the
GStreamer playback pipeline with ReplayGain/limiter/equalizer, GSettings and
libsecret) and replaces the GTK UI with Qt. The GLib-based subsystems are driven
from the Qt event loop by pumping the GLib main context from a `QTimer`.

## Status

- Full core player: login, stations, gapless playback, ratings, album art, preferences.
- All **10** of Pithos' plugins ported: MPRIS (with media keys, hide-on-close and
  live playlists), media keys, notifications, system-tray icon, 10-band equalizer,
  Last.fm scrobbling, screensaver inhibit, screensaver pause, ReplayGain volume
  normalization, and journald logging — with an in-app plugin manager.
- Standalone: its own `io.github.k5blazerfl.Pyrrha` GSettings/keyring/desktop
  identity, a one-time migration from an existing Pithos config, and a vendored
  backend (no dependency on the Pithos package at runtime).

## Quick start

```sh
python3 -m venv --system-site-packages .venv-qt
.venv-qt/bin/pip install -e .   # installs Pyrrha + PySide6, creates the `pyrrha` command
./install.sh                    # installs the GSettings schema, .desktop file & icon (user-local)
.venv-qt/bin/pyrrha             # run (also: ./pyrrha-run, or python -m pyrrha)
.venv-qt/bin/pyrrha --test      # offline mock, no account needed
```

Requires PyGObject with GStreamer 1.x (base + good plugins for AAC) and libsecret
introspection from the system (hence the `--system-site-packages` venv). See
[`pyrrha/README.md`](pyrrha/README.md) for architecture and full details.

## License

GPL-3.0. Pyrrha is a derivative work of Pithos; original copyright and
attribution notices are preserved throughout the source.
