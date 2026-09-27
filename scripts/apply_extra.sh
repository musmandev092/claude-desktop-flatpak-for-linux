#!/bin/sh
# Runs ONCE on the user's machine, right after Flatpak downloads the .deb.
# Working directory: /app/extra (no network, no host access).
set -eu

# The .deb is an "ar" archive; bsdtar reads it directly.
# Take data.tar.xz out of it and unpack only the app folder.
bsdtar -xOf claude-desktop.deb data.tar.xz | bsdtar -xf - ./usr/lib/claude-desktop

mv usr/lib/claude-desktop claude-desktop
rm -rf usr claude-desktop.deb
