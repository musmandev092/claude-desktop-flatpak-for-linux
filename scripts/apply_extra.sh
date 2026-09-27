#!/bin/sh
# Runs ONCE on the user's machine, right after Flatpak downloads the .deb.
# Working directory: /app/extra (no network, no host access).
set -eu

# The .deb is an "ar" archive; bsdtar reads it directly.
# Remember Claude's version (from the package label), then unpack the app folder.
bsdtar -xOf claude-desktop.deb control.tar.xz | bsdtar -xOf - ./control \
    | sed -n 's/^Version: //p' > claude-version
bsdtar -xOf claude-desktop.deb data.tar.xz | bsdtar -xf - ./usr/lib/claude-desktop

mv usr/lib/claude-desktop claude-desktop-orig
rm -rf usr claude-desktop.deb

# Cowork: build a twin of the app folder out of hard links (same files on disk,
# no extra space) and give only the twin a patched app.asar. The launcher runs
# the twin, and can always fall back to the untouched original.
cp -al claude-desktop-orig claude-desktop
R=claude-desktop/resources
if python3 /app/bin/cowork-patch claude-desktop-orig/resources/app.asar "$R/app.asar.new" > cowork-status 2>&1; then
    rm "$R/app.asar"                  # drop the hard link, not the original
    mv "$R/app.asar.new" "$R/app.asar"
else
    rm -f "$R/app.asar.new"           # twin stays identical to the original
fi
