#!/bin/bash
# Syntax checks that need no Flatpak: every shell script, every script that is
# embedded in host-run as a string (they must not be empty, and must parse on
# their own – a stray apostrophe once broke one), and the Python files.
set -eu
cd "$(dirname "$0")/.."
for f in scripts/host-run scripts/claude-desktop.sh scripts/apply_extra.sh scripts/cowork-helper-shim tests/*.sh; do
    bash -n "$f"
done
# shellcheck disable=SC2016  # the sed patterns are meant literally
extract='/^LOAD_ENV=/,/^$/p;/^FAST=/,/"\$job"'"'"'$/p;/^WATCHDOG=/,/^exit "\$s"'"'"'$/p;/^LAUNCH=/,/^exit "\$r"'"'"'$/p'
for v in FAST LAUNCH WATCHDOG LOAD_ENV; do
    body=$(bash -c "$(sed -n "$extract" scripts/host-run)
printf '%s' \"\$$v\"")
    if [ -z "$body" ] || ! printf '%s\n' "$body" | bash -n; then
        echo "embedded script $v in host-run is missing or does not parse" >&2
        exit 1
    fi
done
python3 -m py_compile scripts/host-bridge scripts/cowork-patch site/build.py tests/check-site.py tests/fuzz-in-sandbox.py
find . -name __pycache__ -type d -prune -exec rm -rf {} +
echo "lint: all scripts parse"
