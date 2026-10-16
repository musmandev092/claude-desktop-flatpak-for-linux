#!/bin/sh
set -eu

bsdtar -xOf claude-desktop.deb 'control.tar*' | bsdtar -xOf - ./control \
    | sed -n 's/^Version: //p' > claude-version
bsdtar -xOf claude-desktop.deb 'data.tar*' | bsdtar -xf - ./usr/lib/claude-desktop

mv usr/lib/claude-desktop claude-desktop
rm -rf usr claude-desktop.deb

