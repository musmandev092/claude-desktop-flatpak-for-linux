#!/bin/bash
set -eu
cd "$(dirname "$0")/.."
for f in scripts/host-run scripts/claude-desktop.sh scripts/apply_extra.sh tests/*.sh; do
    bash -n "$f"
done
# shellcheck disable=SC2016
body=$(bash -c "$(sed -n '/^LOAD_ENV=/,/exec "\$@"'"'"'$/p' scripts/host-run)
printf '%s' \"\$LOAD_ENV\"")
if [ -z "$body" ] || ! printf '%s\n' "$body" | bash -n; then
    echo "LOAD_ENV in host-run is missing or does not parse" >&2
    exit 1
fi
python3 -m py_compile scripts/host-bridge tests/fuzz-in-sandbox.py
find . -name __pycache__ -type d -prune -exec rm -rf {} +
echo "lint: all scripts parse"

