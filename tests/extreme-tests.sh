#!/bin/bash
# Extreme / edge-case tests for the INSTALLED Flatpak. Run on the host:
#     tests/extreme-tests.sh
# Close Claude first. Your settings.conf is backed up and restored.
# Creates (and removes) a throwaway toolbox called "claude-test".
set -u
APP_ID=io.github.musmandev092.ClaudeDesktop
HERE=$(cd "$(dirname "$0")" && pwd)
LOG="$HOME/.var/app/$APP_ID/config/Claude/logs/main.log"
SETTINGS="$HOME/.config/claude-desktop-flatpak/settings.conf"
DATA="$HOME/.var/app/$APP_ID/data"
RT="$XDG_RUNTIME_DIR/app/$APP_ID"
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1${2:+  — $2}"; }
skip() { echo "SKIP  $1${2:+  — $2}"; }

if pgrep -x claude-desktop >/dev/null; then echo "Close Claude first."; exit 2; fi
backup=$(mktemp); cp "$SETTINGS" "$backup" 2>/dev/null || : > "$backup"
restore() {
    cp "$backup" "$SETTINGS"; rm -f "$backup"
    flatpak kill "$APP_ID" 2>/dev/null
    toolbox rm -f claude-test >/dev/null 2>&1
}
trap restore EXIT
set_conf() { mkdir -p "$(dirname "$SETTINGS")"; printf '%s\n' "$@" > "$SETTINGS"; }

# Start the app, wait, report which binary runs; then close it
launch() {   # launch <seconds> [flatpak run options...]
    local wait=$1; shift
    before=$(wc -l < "$LOG" 2>/dev/null || echo 0)
    flatpak run "$@" "$APP_ID" >"$RT.launch.log" 2>&1 &
    sleep "$wait"
    NEW=$(tail -n +"$((before + 1))" "$LOG" 2>/dev/null)
    RUNNING=$(pgrep -a claude-desktop | grep -oE '/app/extra/claude-desktop(-orig)?/claude-desktop' | sort -u | head -1)
}
opened() { echo "$NEW" | grep -q window_visible_ms; }
close() { flatpak kill "$APP_ID" 2>/dev/null; sleep 3; }
inside() { flatpak run --command=bash "$APP_ID" -c "$1" 2>&1; }

{
echo "── Inside the sandbox: arguments, data, signals, load, MCP, patcher ──"
set_conf TOOLBOX=dev
flatpak run --command=bash "$APP_ID" "$HERE/extreme-in-sandbox.sh"

echo "── Secrets never appear in the process list ──"
for box in dev ""; do
    set_conf "TOOLBOX=$box"
    inside 'head -c 12 /dev/urandom | od -An -tx1 | tr -d " \n" > $XDG_RUNTIME_DIR/app/$FLATPAK_ID/secret
            MY_API_KEY=$(cat $XDG_RUNTIME_DIR/app/$FLATPAK_ID/secret) PATH=/app/bin:$PATH host-run sleep 6 </dev/null' &
    sleep 3.5
    secret=$(cat "$RT/secret" 2>/dev/null)
    leaks=$(ps -eo args | grep -cF -- "${secret:-none}" )
    # the grep itself is one match
    [ -n "$secret" ] && [ "$leaks" -le 1 ] && pass "secrets: API key not visible in ps (${box:-host} mode)" \
        || fail "secrets: API key visible in ps (${box:-host} mode)" "$((leaks-1)) processes"
    wait; rm -f "$RT/secret"
done
set_conf TOOLBOX=dev

echo "── Settings and toolbox problems ──"
set_conf TOOLBOX=this-toolbox-does-not-exist
rm -f "$HOME/.var/app/$APP_ID/cache/host-bridge/this-toolbox-does-not-exist."*
launch 25
opened && pass "missing toolbox: Claude still opens" || fail "missing toolbox: Claude opens"
close

rm -f "$SETTINGS"
launch 25
opened && pass "no settings file: Claude opens (plugins run on the host)" || fail "no settings file"
out=$(inside 'host-bridge link && ls $XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-bin/ | grep -c .')
[ "${out:-0}" -gt 50 ] && pass "no settings file: $out host commands linked" || fail "no settings file: host links" "$out"
close

printf 'garbage ===\n\x01\x02 TOOLBOX\nTOOLBOX=dev\nCOWORK=maybe\n' > "$SETTINGS"
launch 25
opened && [ "$RUNNING" = /app/extra/claude-desktop/claude-desktop ] \
    && pass "garbage in settings: ignored, Claude + Cowork run" || fail "garbage in settings" "running=$RUNNING"
close

echo "── A toolbox that is stopped, then one without the tools ──"
if toolbox create -y claude-test >/dev/null 2>&1; then
    podman stop claude-test >/dev/null 2>&1
    set_conf TOOLBOX=claude-test
    rm -f "$HOME/.var/app/$APP_ID/cache/host-bridge/claude-test."*
    out=$(inside 'host-bridge link; export PATH=/app/bin:$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-bin:$PATH; python3 -c "import os; print(\"cold:\", os.path.exists(\"/run/.containerenv\"))"')
    echo "$out" | grep -q 'cold: True' && pass "stopped toolbox is started automatically" || fail "stopped toolbox cold start" "$out"
    out=$(inside 'export PATH=/app/bin:$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-bin:$PATH; host-run npx --version; echo rc=$?')
    echo "$out" | grep -q 'rc=127' && pass "tool missing in toolbox: clean 'not found' (127)" || fail "missing tool in toolbox" "$out"
    podman stop claude-test >/dev/null 2>&1
    out=$(inside 'export PATH=/app/bin:$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-bin:$PATH; echo "{}" | python3 -c "import sys; print(\"piped:\", sys.stdin.read().strip())"')
    echo "$out" | grep -q 'piped: {}' && pass "MCP-style pipe works while toolbox cold-starts" || fail "pipe during cold start" "$out"
else
    skip "stopped toolbox tests" "could not create a test toolbox"
fi
set_conf TOOLBOX=dev

echo "── Launching the app in unusual ways ──"
launch 25
first=$RUNNING
flatpak run "$APP_ID" >/dev/null 2>&1; rc=$?
sleep 3
n=$(pgrep -f '/app/extra/claude-desktop.*/claude-desktop$' | wc -l)
[ "$rc" -eq 0 ] && [ "$n" -eq 1 ] && [ ! -e "$DATA/cowork-broken" ] \
    && pass "second launch: hands over to the running app, no false Cowork fallback" \
    || fail "second launch" "rc=$rc main-processes=$n broken=$(cat "$DATA/cowork-broken" 2>/dev/null)"
out=$(inside 'export PATH=/app/bin:$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-bin:$PATH; for i in $(seq 30); do node -e "" || echo MISSING; done' )
echo "$out" | grep -q MISSING && fail "relink while running: a command went missing" || pass "relink while running: commands never go missing"
close

launch 25 --socket=x11 --nosocket=wayland
opened && pass "X11 desktop (no Wayland): Claude opens" || fail "X11 only" "$(tail -3 "$RT.launch.log")"
close

launch 25 --nodevice=all --device=dri
opened && pass "no KVM/vsock devices: Claude still opens (only Cowork unavailable)" || fail "no KVM devices"
close

pkill -9 -f 'extra/claude-desktop' 2>/dev/null; sleep 2
launch 25
opened && pass "restart after a hard kill (-9): Claude opens" || fail "restart after kill -9"
close

echo "── Crash safety net (launcher logic with a fake app that crashes) ──"
out=$(inside '
    R=$XDG_RUNTIME_DIR/app/$FLATPAK_ID
    # a fake app: the patched one crashes, the original works
    printf "%s\n" "#!/bin/sh" "case \"\$1\" in *-orig*) echo RAN-ORIGINAL; exit 0;; *) echo RAN-PATCHED-CRASH; exit 1;; esac" > $R/fake-app
    chmod +x $R/fake-app
    sed -e "s#zypak-wrapper \"\$APP/claude-desktop\"#$R/fake-app \"\$APP\"#" \
        -e "s#exec zypak-wrapper /app/extra/claude-desktop-orig/claude-desktop#exec $R/fake-app /app/extra/claude-desktop-orig#" \
        /app/bin/claude-desktop > $R/launcher-test.sh
    rm -f /var/data/cowork-broken
    L=$XDG_CONFIG_HOME/Claude/SingletonLock
    ln -sfn fake-host-1 $L; bash $R/launcher-test.sh; echo "handover-marker=$(cat /var/data/cowork-broken 2>/dev/null || echo none)"; rm -f $L
    bash $R/launcher-test.sh; echo "rc=$?"
    echo "marker=$(cat /var/data/cowork-broken)"
    bash $R/launcher-test.sh
    rm -f /var/data/cowork-broken $R/launcher-test.sh $R/fake-app')
echo "$out" | grep -q RAN-PATCHED-CRASH && echo "$out" | grep -q 'rc=0' && echo "$out" | grep -q "marker=$(cat "$(flatpak info --show-location "$APP_ID")/files/extra/claude-version")" \
    && pass "crash: patched app crashes twice → original starts, version remembered" || fail "crash fallback" "$out"
echo "$out" | grep -q 'handover-marker=none' \
    && pass "crash: quick exit while another Claude runs is NOT treated as a crash" || fail "crash: handover false alarm" "$out"
[ "$(echo "$out" | grep -c RAN-PATCHED-CRASH)" -eq 3 ] && [ "$(echo "$out" | grep -c RAN-ORIGINAL)" -eq 2 ] \
    && pass "crash: next start goes straight to the original (no crash loop)" || fail "crash: no crash loop" "$out"
} 2>&1 | tee "$RT.extreme.log"

echo
p=$(grep -c '^PASS' "$RT.extreme.log"); f=$(grep -c '^FAIL' "$RT.extreme.log"); s=$(grep -c '^SKIP' "$RT.extreme.log")
echo "Result: $p passed, $f failed, $s skipped"
[ "$f" -eq 0 ]
