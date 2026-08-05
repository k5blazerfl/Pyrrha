#!/bin/sh
# Install Pyrrha's user-local resources: the GSettings schema (compiled), the
# desktop file and the app icon. No root required (everything goes under
# $XDG_DATA_HOME, default ~/.local/share). Safe to re-run.
set -e

here=$(dirname "$(readlink -f "$0")")
data="$here/pyrrha/data"
datahome="${XDG_DATA_HOME:-$HOME/.local/share}"

APP_ID=io.github.k5blazerfl.Pyrrha

# --- GSettings schema ---
schemadir="$datahome/glib-2.0/schemas"
mkdir -p "$schemadir"
cp "$data/$APP_ID.gschema.xml" "$schemadir/"
glib-compile-schemas "$schemadir"
echo "Installed + compiled GSettings schema into $schemadir"

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
