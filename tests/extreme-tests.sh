#!/bin/bash
set -u
APP_ID=io.github.musmandev092.ClaudeDesktop
HERE=$(cd "$(dirname "$0")" && pwd)
LOG="$HOME/.var/app/$APP_ID/config/Claude/logs/main.log"
RT="$XDG_RUNTIME_DIR/app/$APP_ID"
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1${2:+  — $2}"; }
skip() { echo "SKIP  $1${2:+  — $2}"; }

if pgrep -x claude-desktop >/dev/null; then echo "Close Claude first."; exit 2; fi
trap 'flatpak kill "$APP_ID" 2>/dev/null' EXIT

waitfor() { local n=$(( $1 * 5 )); shift; until "$@"; do n=$((n - 1)); [ $n -le 0 ] && return 1; sleep 0.2; done; }
gone() { ! pgrep -f '/app/extra/claude-desktop/claude-desktop' >/dev/null; }
launch() {
    local wait=$1; shift
    before=$(wc -l < "$LOG" 2>/dev/null || echo 0)
    flatpak run "$@" "$APP_ID" >"$RT.launch.log" 2>&1 &
    shown() { tail -n +"$((before + 1))" "$LOG" 2>/dev/null | grep -q window_visible_ms; }
    waitfor "$wait" shown
    NEW=$(tail -n +"$((before + 1))" "$LOG" 2>/dev/null)
    RUNNING=$(pgrep -a claude-desktop | grep -oE '/app/extra/claude-desktop/claude-desktop' | sort -u | head -1)
}
opened() { echo "$NEW" | grep -q window_visible_ms; }
close() { flatpak kill "$APP_ID" 2>/dev/null; waitfor 10 gone; }
inside() { flatpak run --command=bash "$APP_ID" -c "$1" 2>&1; }

{
echo "── Inside the sandbox: arguments, data, signals, load, MCP ──"
flatpak run --command=bash "$APP_ID" "$HERE/extreme-in-sandbox.sh"

echo "── Secrets never appear in the process list ──"
inside 'head -c 12 /dev/urandom | od -An -tx1 | tr -d " \n" > $XDG_RUNTIME_DIR/app/$FLATPAK_ID/secret
        MY_API_KEY=$(cat $XDG_RUNTIME_DIR/app/$FLATPAK_ID/secret) PATH=/app/bridge/bin:/app/bin:$PATH host-run sleep 6 </dev/null' &
started() { [ -s "$RT/secret" ] && pgrep -f 'host-run sleep 6' >/dev/null; }
waitfor 6 started; sleep 0.5
secret=$(cat "$RT/secret" 2>/dev/null)
leaks=$(ps -eo args | grep -cF -- "${secret:-none}")
[ -n "$secret" ] && [ "$leaks" -le 1 ] && pass "secrets: API key not visible in ps" \
    || fail "secrets: API key visible in ps" "$((leaks-1)) processes"
wait; rm -f "$RT/secret"

echo "── Launching the app in unusual ways ──"
launch 25
: "first launch ran: $RUNNING"
flatpak run "$APP_ID" >/dev/null 2>&1; rc=$?
mains() { pgrep -af '/app/extra/claude-desktop/claude-desktop' | grep -vc -- '--type='; }
one() { [ "$(mains)" -eq 1 ]; }
waitfor 3 one
n=$(mains)
[ "$rc" -eq 0 ] && [ "$n" -eq 1 ] \
    && pass "second launch: hands over to the running app" \
    || fail "second launch" "rc=$rc main-processes=$n"
out=$(inside 'export PATH=/app/bridge/bin:/app/bin:$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-bin:$PATH; for i in $(seq 30); do node -e "" || echo MISSING; done' )
echo "$out" | grep -q MISSING && fail "relink while running: a command went missing" || pass "relink while running: commands never go missing"
close

launch 25 --socket=x11 --nosocket=wayland
opened && pass "X11 desktop (no Wayland): Claude opens" || fail "X11 only" "$(tail -3 "$RT.launch.log")"
close

pkill -9 -f 'extra/claude-desktop' 2>/dev/null; waitfor 5 gone
launch 25
opened && pass "restart after a hard kill (-9): Claude opens" || fail "restart after kill -9"
close

} 2>&1 | tee "$RT.extreme.log"

echo
p=$(grep -c '^PASS' "$RT.extreme.log"); f=$(grep -c '^FAIL' "$RT.extreme.log"); s=$(grep -c '^SKIP' "$RT.extreme.log")
echo "Result: $p passed, $f failed, $s skipped"
[ "$f" -eq 0 ]

