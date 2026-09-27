#!/bin/bash
# Full test of the INSTALLED Flatpak. Run it on the host:
#     tests/run-tests.sh            all tests
#     tests/run-tests.sh --no-gui   skip launching the app window
set -u
APP_ID=io.github.musmandev092.ClaudeDesktop
HERE=$(cd "$(dirname "$0")" && pwd)
LOG="$HOME/.var/app/$APP_ID/config/Claude/logs/main.log"

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1${2:+  — $2}"; }
skip() { echo "SKIP  $1${2:+  — $2}"; }

results=$(mktemp)
{
    if ! flatpak info "$APP_ID" >/dev/null 2>&1; then
        fail "installed" "run the install steps in README.md first"
        exit 1
    fi
    pass "installed: $(flatpak info "$APP_ID" | sed -n 's/^ *Commit: //p' | cut -c1-12)"

    # Everything that runs inside the sandbox
    flatpak run --command=bash "$APP_ID" "$HERE/in-sandbox.sh"

    # Plugin cleanup: a process started through the bridge must stop when the app exits
    if pgrep -x claude-desktop >/dev/null; then
        skip "cleanup: plugins stop when Claude exits" "close Claude first to run this test"
    else
        marker="cleanup-test-$$"
        flatpak run --command=bash "$APP_ID" -c "
            export PATH=/app/bin:\$XDG_RUNTIME_DIR/app/\$FLATPAK_ID/host-bin:\$PATH
            host-run python3 -c 'import time; time.sleep(600)  # $marker' </dev/null >/dev/null 2>&1 &
            sleep 60" &
        sleep 6
        if pgrep -f "$marker" | xargs -r ps -o comm= -p | grep -q python; then
            flatpak kill "$APP_ID"; sleep 7
            if pgrep -f "$marker" | xargs -r ps -o comm= -p | grep -q python; then
                fail "cleanup: plugins stop when Claude exits"; pkill -f "$marker"
            else
                pass "cleanup: plugins stop when Claude exits"
            fi
        else
            fail "cleanup: test process did not start"
        fi
        wait 2>/dev/null
    fi

    # The real app window
    if [ "${1:-}" = --no-gui ]; then
        skip "gui: app window opens" "--no-gui"
    elif pgrep -x claude-desktop >/dev/null; then
        skip "gui: app window opens" "Claude is already running"
    else
        before=$(wc -l < "$LOG" 2>/dev/null || echo 0)
        flatpak run "$APP_ID" >/dev/null 2>&1 &
        sleep 30   # the first start after an install is slower
        new=$(tail -n +"$((before + 1))" "$LOG" 2>/dev/null)
        echo "$new" | grep -q window_visible_ms && pass "gui: app window opens" || fail "gui: app window opens"
        if pgrep -af 'extra/claude-desktop/claude-desktop' | grep -qv orig; then
            pass "gui: patched app (Cowork) is the one running"
        else
            fail "gui: patched app is running" "fell back to the original"
        fi
        echo "$new" | grep -q 'Shell environment extraction failed' \
            && fail "gui: Claude Code reads your shell" || pass "gui: Claude Code reads your shell"
        flatpak kill "$APP_ID"
    fi
} 2>&1 | tee "$results"

echo
p=$(grep -c '^PASS' "$results"); f=$(grep -c '^FAIL' "$results"); s=$(grep -c '^SKIP' "$results")
echo "Result: $p passed, $f failed, $s skipped"
rm -f "$results"
[ "$f" -eq 0 ]
