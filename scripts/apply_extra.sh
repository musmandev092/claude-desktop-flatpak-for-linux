#!/bin/sh
# Runs ONCE on the user's machine, right after Flatpak downloads the .deb.
# Working directory: /app/extra (no network, no host access).
set -eu

# The .deb is an "ar" archive; bsdtar reads it directly.
# Remember Claude's version (from the package label), then unpack the app folder.
bsdtar -xOf claude-desktop.deb control.tar.xz | bsdtar -xOf - ./control \
    | sed -n 's/^Version: //p' > claude-version
bsdtar -xOf claude-desktop.deb data.tar.xz | bsdtar -xf - ./usr/lib/claude-desktop

# Claude runs exactly as Anthropic ships it: nothing inside the app is changed
mv usr/lib/claude-desktop claude-desktop
rm -rf usr claude-desktop.deb
