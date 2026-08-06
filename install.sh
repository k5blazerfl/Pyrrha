#!/bin/sh
# Install Pyrrha's user-local resources: the desktop file and the app icon. No
# root required (everything goes under $XDG_DATA_HOME, default ~/.local/share).
# Safe to re-run. Configuration is stored via QSettings (~/.config), so there is
# no GSettings schema to install or compile.
set -e

here=$(dirname "$(readlink -f "$0")")
data="$here/pyrrha/data"
datahome="${XDG_DATA_HOME:-$HOME/.local/share}"

APP_ID=io.github.k5blazerfl.Pyrrha

# --- Desktop file ---
appsdir="$datahome/applications"
mkdir -p "$appsdir"
cp "$data/$APP_ID.desktop" "$appsdir/"
echo "Installed desktop file into $appsdir"

# --- Icon ---
icondir="$datahome/icons/hicolor/256x256/apps"
mkdir -p "$icondir"
cp "$here/pyrrha/icons/pyrrha.png" "$icondir/$APP_ID.png"
echo "Installed 256x256 icon into $icondir"

# Best-effort cache refresh (ignored if the tools are absent).
gtk-update-icon-cache -qtf "$datahome/icons/hicolor" 2>/dev/null || true
update-desktop-database -q "$appsdir" 2>/dev/null || true

echo "Done. Pyrrha resources installed for the current user."
