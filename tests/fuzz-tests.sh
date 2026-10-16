#!/bin/bash
set -u
APP_ID=io.github.musmandev092.ClaudeDesktop
HERE=$(cd "$(dirname "$0")" && pwd)
exec flatpak run --command=/usr/bin/python3 "$APP_ID" "$HERE/fuzz-in-sandbox.py" "$@"

