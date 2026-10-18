#!/bin/sh
set -eu

bsdtar -xOf claude-desktop.deb 'control.tar*' | bsdtar -xOf - ./control \
    | sed -n 's/^Version: //p' > claude-version
bsdtar -xOf claude-desktop.deb 'data.tar*' | bsdtar -xf - ./usr/lib/claude-desktop

mv usr/lib/claude-desktop claude-desktop
rm -rf usr claude-desktop.deb

# Electron names the Wayland app ID after package.json's desktopName; point it
# at our desktop file so docks show the right icon. Not fatal if it fails.
/app/bin/patch-electron-desktop-filename --desktop-filename io.github.musmandev092.ClaudeDesktop \
    claude-desktop/resources/app.asar || echo "apply_extra: could not set desktopName" >&2
