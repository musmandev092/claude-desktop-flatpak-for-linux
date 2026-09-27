#!/bin/sh
# Launcher: runs every time the user opens the app.

# Private temp folder for this app (shared by all of its processes)
export TMPDIR="$XDG_RUNTIME_DIR/app/$FLATPAK_ID"

# Tell Electron our desktop file name, so GNOME shows our icon on the window
export CHROME_DESKTOP="$FLATPAK_ID.desktop"

# zypak lets Chromium's own sandbox work inside the Flatpak sandbox
exec zypak-wrapper /app/extra/claude-desktop/claude-desktop "$@"
