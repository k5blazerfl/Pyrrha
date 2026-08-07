# Pyrrha — architecture

Pyrrha is a skinnable Qt (PySide6) audio player that plays both Pandora radio and
local files. It **began** as a GTK→Qt port of
[Pithos](https://pithos.github.io), the native Pandora client, and still builds
on Pithos' core (Pandora API, GStreamer pipeline, settings, credentials). Layered
on top — with no analog in Pithos — are local-file playback and a Winamp 2.x
`.wsz` skin engine (classic and modern skinned shells alongside the modern Qt
window). This document covers the shared core; see the top-level
[`README.md`](../README.md) for the feature overview.

## Design (the Pithos-derived core)

Pyrrha deliberately keeps the parts of Pithos that have nothing to do with the
GTK widget toolkit and swaps **only the view layer** for Qt:

| Concern | Approach |
| --- | --- |
| Pandora API + Blowfish | **Reused unchanged** from `pithos.pandora` |
| Audio playback | **GStreamer**, identical pipeline (`playbin3` → `rgvolume` → `rglimiter` → `equalizer-10bands` → `audioconvert` → `audioresample` → `autoaudiosink`) |
| Settings | **GSettings** (own `io.github.k5blazerfl.Pyrrha` schema; a one-time migration imports an existing Pithos config) |
| Credentials | **libsecret** (own `io.github.k5blazerfl.Pyrrha.Account` schema) |
| Background work | Threaded worker marshaling results with `GLib.idle_add` |
| UI | **Qt / PySide6** widgets |

The key that makes this work: GStreamer, GSettings, libsecret and the worker all
deliver callbacks through a GLib `MainContext`. Since Qt owns the event loop,
`glib_bridge.GLibBridge` iterates that context from a short `QTimer`, so every one
of those GLib subsystems keeps functioning unchanged. No GLib main loop runs.

## Layout

```
pyrrha/
  __main__.py          entry point (argparse, QApplication, GLib bridge)
  glib_bridge.py       pumps the GLib main context from a QTimer
  worker.py            threaded worker (GLib.idle_add marshaling)
  keyring.py           libsecret credential storage (no GTK)
  models.py            SongsModel + album-art painting delegate
  stations_popover.py  popup station chooser
  window.py            the main window (port of Pithos' PithosWindow)
  appicon.py           single source for the app icon (icons/pyrrha.png)
  migrate.py           one-time import of an existing Pithos config/credentials
  pandora/             vendored Pandora API client (from Pithos; pure Python)
  dbus_util/           vendored Gio D-Bus service helper (from Pithos)
  data/                GSettings schema + .desktop file (installed by install.sh)
  dialogs/
    preferences.py     account / quality / proxy settings
    stations.py        manage stations (rename, QuickMix, add, delete)
    search.py          search for a station seed
    about.py           about box
```

The Pandora backend and the D-Bus service helper are **vendored** into
`pyrrha/pandora/` and `pyrrha/dbus_util/` (copied from Pithos, GPL/LGPL headers
intact), so Pyrrha no longer imports the `pithos` package — the `pithos-master`
tree is not needed at runtime. The offline `--test` mode uses a headless mock
(`pandora/fake.py`) with no GTK.

## Running

A virtualenv with PySide6 and access to the system `gi`/GStreamer bindings is
used:

```sh
python3 -m venv --system-site-packages .venv-qt
.venv-qt/bin/pip install -e .   # installs Pyrrha + PySide6, creates the `pyrrha` command
./install.sh                    # one-time: installs the GSettings schema, desktop file & icon (user-local, no root)
.venv-qt/bin/pyrrha             # or ./pyrrha-run, or python -m pyrrha
.venv-qt/bin/pyrrha --verbose   # -v info, -d debug
.venv-qt/bin/pyrrha --test      # offline mock (no network/account)
```

`pip install -e .` reads `pyproject.toml`, pulls PySide6, and creates a `pyrrha`
entry point (`pyrrha.__main__:main`). PyGObject/GStreamer/libsecret come from the
system (hence the `--system-site-packages` venv). Optional extras: `.[lastfm]`
(pylast) and `.[journald]` (systemd-python). After `./install.sh`, Pyrrha also
appears in the application menu (the `.desktop` file launches the `pyrrha`
entry point).

`./install.sh` is **required before the first run** — it compiles and installs
Pyrrha's own `io.github.k5blazerfl.Pyrrha` GSettings schema (plus the `.desktop`
file and icon) under `~/.local/share`. On first launch, if an existing Pithos
config is present it is migrated over automatically (non-destructively).

Requirements on the host: PyGObject with GStreamer 1.x (base + good plugins for
AAC) and libsecret introspection.

## Status

**Working:** login flow, keyring, station list + switching, playback with the
full ReplayGain/limiter/equalizer pipeline, buffering state machine, transport
(play/pause/skip), volume (cubic scale), ratings (love/ban/tired/unrate),
bookmarks, create-station-from-song/artist, album art with caching, song context
menu, preferences (account/quality/proxy), stations management dialog, search,
and the about box.

**Plugins** — all 10 of Pithos' plugins are ported (details below):

- **MPRIS** (`plugins/mpris.py`) — full `org.mpris.MediaPlayer2` + `.Player`
  (plus Playlists / TrackList and Pithos' ratings extension), reusing Pithos'
  pure-Gio D-Bus service helper. This is also what makes hardware **media keys**
  work on KDE Plasma and modern GNOME (the desktop routes Play/Pause/Next to the
  registered MPRIS player). Verified end-to-end: external `gdbus` PlayPause/Next
  calls pause/resume/skip live playback.
- **Media keys** (`plugins/mediakeys.py`) — the classic GNOME/MATE
  SettingsDaemon grab, with Qt-based focus tracking replacing the GTK/X11 bits.
  On KDE (no such daemon) it cleanly disables and MPRIS handles the keys.
- **Notifications** (`plugins/notify.py`) — desktop notifications on song change
  via the freedesktop `org.freedesktop.Notifications` D-Bus service (Pithos used
  `Gio.Application`, which Qt lacks). Artist as summary, title as body, album art
  once it arrives (refreshed in place via `replaces_id`), a **Skip** action and
  click-to-focus. Only shown while the window is inactive. **Off by default**
  (matching Pithos' schema) — turn it on in **Preferences → Plugins**.

These load at startup via `plugin_loader.py` and honour their `io.github.Pithos`
plugin GSettings `enabled` flags (mpris + mediakeys default on, notify off).

- **Equalizer** (`plugins/equalizer.py`) — a 10-band graphic EQ (−24…+12 dB)
  driving the `equalizer-10bands` element that's always in the pipeline. Enabling
  applies the saved curve; disabling flattens every band. Its *Configure…* dialog
  (the first plugin to use that hook) is 10 vertical sliders with live dB and
  frequency labels (29 Hz–15 kHz), Reset/Close, persisted to the plugin's `data`
  GSetting. Off by default.

- **Tray icon** (`plugins/notification_icon.py`) — a system-tray icon via
  `QSystemTrayIcon` (Qt speaks the KDE StatusNotifierItem protocol natively, so
  no hand-rolled SNI/dbusmenu like Pithos). Left-click toggles the window; the
  context menu has Play/Pause (label tracks state), Skip, Love, Ban, Tired,
  Show/Hide and Quit; the tooltip shows the current track. While the icon is
  shown, **closing the window hides it to the tray** instead of quitting (via a
  close-interceptor hook on the window). *Configure…* switches between the
  symbolic and full-colour icons. Off by default.

- **Last.fm** (`plugins/lastfm.py`) — scrobbling via `pylast` (optional dep; the
  plugin disables itself with a note if missing). *Configure…* runs Last.fm's
  web-auth flow (Authorize → browser → Finish), storing the session key; then
  sends now-playing on song change and scrobbles on song end. Off by default.
- **Screensaver inhibit** (`plugins/inhibit_screensaver.py`) — keeps the session
  from going idle while playing, via the `org.freedesktop.ScreenSaver` D-Bus
  interface (Pithos used `GtkApplication.inhibit`). Off by default.
- **Journald logging** (`plugins/journald_logging.py`) — routes logs to the
  systemd journal (optional `systemd` dep); *Configure…* picks the level. Off by
  default; self-disables with a note where `systemd` is absent.
- **Auto volume normalization** (`plugins/auto_volume_normalization.py`) —
  ReplayGain loudness leveling: turns on `rglimiter` and feeds each track's
  `trackGain` to `rgvolume` (both already in the pipeline). Off by default.
- **Screensaver pause** (`plugins/screensaver_pause.py`) — pauses playback while
  the screensaver is active and resumes after, via the screensaver's
  `ActiveChanged` D-Bus signal (freedesktop + GNOME variants; Pithos used a
  GtkApplication property). In-tree schema child.

**Plugin manager** — the Preferences dialog now has an **Account** / **Plugins**
tab pair (`dialogs/preferences.py`). Each plugin gets a row with an on/off toggle
bound to its `enabled` GSetting (enabling/disabling the plugin live), a
*Configure…* button when the plugin exposes a settings dialog, and a
disabled/tooltip state when the plugin failed to load (e.g. media keys on KDE,
which shows *"No GNOME/MATE media-key daemon found (KDE uses MPRIS)"*).

All **10** of Pithos' plugins are now ported. MPRIS also supports **Hide-on-Close**
(a *Configure…* toggle that hides the window instead of quitting, via the window's
close-interceptor hook) and **live Playlists** (station add/rename/remove are
pushed to the MPRIS Playlists interface as they happen).

**Still deferred to later phases:**

- **Window position restore** — Pithos persisted `win-pos`; omitted (it was
  X11-only and a no-op under Wayland anyway).
- **Explicit-content-filter PIN entry** — the checkbox reflects and toggles
  state; PIN-protected accounts are shown read-only.
