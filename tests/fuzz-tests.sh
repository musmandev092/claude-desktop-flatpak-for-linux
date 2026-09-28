#!/bin/bash
# 10,000 generated extreme scenarios against the installed Flatpak:
#     tests/fuzz-tests.sh                     everything (seed 20260928)
#     tests/fuzz-tests.sh --seed 7            another set of 10,000
#     tests/fuzz-tests.sh --only 1234         replay one scenario
#     tests/fuzz-tests.sh --count 500         a quick run
#     tests/fuzz-tests.sh --project           test scripts/ in this folder
# Claude may stay open. Needs the 'dev' toolbox running; never starts or
# stops your toolboxes and never touches your settings.conf.
set -u
APP_ID=io.github.musmandev092.ClaudeDesktop
HERE=$(cd "$(dirname "$0")" && pwd)
exec flatpak run --command=/usr/bin/python3 "$APP_ID" "$HERE/fuzz-in-sandbox.py" "$@"
