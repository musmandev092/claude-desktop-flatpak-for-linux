#!/bin/bash
set -u
APP_ID=io.github.musmandev092.ClaudeDesktop
HERE=$(cd "$(dirname "$0")" && pwd)
LOG="$HOME/.var/app/$APP_ID/config/Claude/logs/main.log"

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1${2:+  — $2}"; }
skip() { echo "SKIP  $1${2:+  — $2}"; }
waitfor() { local n=$(( $1 * 5 )); shift; until "$@"; do n=$((n - 1)); [ $n -le 0 ] && return 1; sleep 0.2; done; }
plugin_alive() { pgrep -f "$marker" | xargs -r ps -o comm= -p | grep -q python; }
plugin_gone() { ! plugin_alive; }

results=$(mktemp)
{
    if ! flatpak info "$APP_ID" >/dev/null 2>&1; then
        fail "installed" "run the install steps in README.md first"
        exit 1
    fi
    pass "installed: $(flatpak info "$APP_ID" | sed -n 's/^ *Commit: //p' | cut -c1-12)"

    flatpak run --command=bash "$APP_ID" "$HERE/in-sandbox.sh"

    if pgrep -x claude-desktop >/dev/null; then
        skip "cleanup: plugins stop when Claude exits" "close Claude first to run this test"
    else
        marker="cleanup-test-$$"
        flatpak run --command=bash "$APP_ID" -c "
            export PATH=/app/bridge/bin:/app/bin:\$XDG_RUNTIME_DIR/app/\$FLATPAK_ID/host-bin:\$PATH
            host-run python3 -c 'import time; time.sleep(600)  # $marker' </dev/null >/dev/null 2>&1 &
            sleep 60" &
        if waitfor 10 plugin_alive; then
            flatpak kill "$APP_ID"
            if ! waitfor 10 plugin_gone; then
                fail "cleanup: plugins stop when Claude exits"; pkill -f "$marker"
            else
                pass "cleanup: plugins stop when Claude exits"
            fi
        else
            fail "cleanup: test process did not start"
        fi
        wait 2>/dev/null
    fi

    if [ "${1:-}" = --no-gui ]; then
        skip "gui: app window opens" "--no-gui"
    elif pgrep -x claude-desktop >/dev/null; then
        skip "gui: app window opens" "Claude is already running"
    else
        before=$(wc -l < "$LOG" 2>/dev/null || echo 0)
        flatpak run "$APP_ID" >/dev/null 2>&1 &
        shown() { tail -n +"$((before + 1))" "$LOG" 2>/dev/null | grep -q window_visible_ms; }
        shell_read() { tail -n +"$((before + 1))" "$LOG" 2>/dev/null | grep -qE 'login-shell env vars|Shell environment extraction failed'; }
        waitfor 60 shown; waitfor 30 shell_read
        new=$(tail -n +"$((before + 1))" "$LOG" 2>/dev/null)
        echo "$new" | grep -q window_visible_ms && pass "gui: app window opens" || fail "gui: app window opens"
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

