#!/bin/bash
# Stress and edge-case checks that run INSIDE the sandbox.
# Started by tests/extreme-tests.sh. Prints PASS / FAIL / SKIP lines.
set -u
cd "$HOME" || exit 1
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1${2:+  — $2}"; }
skip() { echo "SKIP  $1${2:+  — $2}"; }
is() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1" "expected [$3] got [$2]"; fi; }

export HOST_BIN="$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-bin"
host-bridge link >/dev/null 2>&1
export PATH="/app/bin:$HOST_BIN:$PATH"
T=$(mktemp -d -p "$HOME/.var/app/$FLATPAK_ID/cache")
trap 'rm -rf "$T"' EXIT

# ── Arguments and environment that are hard to pass through ──────────────────
arg=$'spaces  and "quotes" \'single\' $dollar `tick` \\back ñ 日本 🎉 *glob* ;semi|pipe&amp'
is "args: special characters survive" "$(python3 -c 'import sys; print(sys.argv[1])' "$arg")" "$arg"
is "args: empty argument survives" "$(python3 -c 'import sys; print(len(sys.argv), repr(sys.argv[1]))' '')" "2 ''"
is "args: leading dash argument" "$(python3 -c 'import sys; print(sys.argv[1])' --weird)" "--weird"
nl=$'line1\nline2'
is "env: value with newline" "$(WEIRD="$nl" python3 -c 'import os; print(os.environ["WEIRD"])')" "$nl"
is "env: value with = and spaces" "$(WEIRD='a=b c=d' python3 -c 'import os; print(os.environ["WEIRD"])')" "a=b c=d"
big=$(head -c 100000 /dev/zero | tr '\0' 'k')
got=$(env B1="$big" B2="$big" B3="$big" B4="$big" B5="$big" B6="$big" B7="$big" B8="$big" B9="$big" B10="$big" \
      python3 -c 'import os; print(sum(len(os.environ["B%d" % i]) for i in range(1, 11)))')
is "env: 10 variables of 100 KB (1 MB total) pass through" "$got" "1000000"

# ── Working directory ────────────────────────────────────────────────────────
mkdir -p "$T/dir with spaces ñ"
is "cwd: folder with spaces/unicode" "$(cd "$T/dir with spaces ñ" && python3 -c 'import os; print(os.path.basename(os.getcwd()))')" "dir with spaces ñ"
is "cwd: sandbox-only /tmp falls back to home" "$(cd /tmp && python3 -c 'import os; print(os.getcwd())')" "$HOME"

# ── Data integrity and volume ────────────────────────────────────────────────
head -c 100000000 /dev/urandom > "$T/blob"
want=$(sha256sum < "$T/blob" | cut -d' ' -f1)
start=$(date +%s.%N)
got=$(python3 -c 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())' < "$T/blob" | sha256sum | cut -d' ' -f1)
secs=$(echo "$(date +%s.%N) - $start" | bc 2>/dev/null || echo "?")
is "pipes: 100 MB of binary data round-trips intact (${secs}s)" "$got" "$want"
is "pipes: NUL bytes survive" "$(printf 'a\0b\0c' | python3 -c 'import sys; print(len(sys.stdin.buffer.read()))')" "5"
is "pipes: stderr kept separate" "$(python3 -c 'import sys; print("out"); print("err", file=sys.stderr)' 2>/dev/null)" "out"

# ── Exit codes and signals ───────────────────────────────────────────────────
for code in 0 1 2 42 126 255; do bash -c "exit $code"; is "exit code $code" "$?" "$code"; done
bash -c 'kill -9 $$'; is "exit code after SIGKILL is 137" "$?" "137"
host-run definitely-not-a-command-xyz 2>/dev/null; rc=$?
[ "$rc" -eq 127 ] && pass "unknown command gives 127" || fail "unknown command gives 127" "got $rc"

python3 -c 'import signal,sys,time
signal.signal(signal.SIGTERM, lambda *a: (print("got-term", flush=True), sys.exit(0)))
print("ready", flush=True); time.sleep(60)' > "$T/sig.out" &
p=$!; for _ in $(seq 40); do grep -q ready "$T/sig.out" 2>/dev/null && break; sleep 0.25; done
kill -TERM $p; wait $p 2>/dev/null
grep -q got-term "$T/sig.out" && pass "signals: SIGTERM reaches the host process" || fail "signals: SIGTERM forwarded" "$(cat "$T/sig.out")"

# ── Load ─────────────────────────────────────────────────────────────────────
start=$(date +%s)
for i in $(seq 50); do (python3 -c "print($i*2)" > "$T/par.$i") & done; wait
ok=0; for i in $(seq 50); do [ "$(cat "$T/par.$i" 2>/dev/null)" = "$((i*2))" ] && ok=$((ok+1)); done
is "load: 50 parallel bridged commands all correct ($(( $(date +%s) - start ))s)" "$ok" "50"
start=$(date +%s.%N); for i in $(seq 20); do git --version >/dev/null; done
per=$(echo "($(date +%s.%N) - $start) / 20" | bc -l 2>/dev/null | cut -c1-5)
pass "load: average bridged call ${per}s (20 sequential git calls)"

# ── MCP server under real conditions ─────────────────────────────────────────
if [ -e "$HOST_BIN/npx" ]; then
    reqs='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}'
    for i in $(seq 2 101); do reqs+=$'\n'"{\"jsonrpc\":\"2.0\",\"id\":$i,\"method\":\"tools/list\"}"; done
    n=$({ echo "$reqs"; sleep 15; } | timeout 120 npx -y @modelcontextprotocol/server-filesystem "$HOME" 2>/dev/null | grep -c '"result"')
    is "mcp: 100 rapid requests to one server, all answered" "$n" "101"
    mkdir -p "$T/mcp dir ñ"; printf 'secret-content-42' > "$T/mcp dir ñ/file.txt"
    r=$({ echo "$reqs" | head -2; echo "{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"tools/call\",\"params\":{\"name\":\"read_text_file\",\"arguments\":{\"path\":\"$T/mcp dir ñ/file.txt\"}}}"; sleep 8; } \
        | timeout 120 npx -y @modelcontextprotocol/server-filesystem "$T" 2>/dev/null)
    echo "$r" | grep -q secret-content-42 && pass "mcp: plugin reads a file in a folder with spaces/unicode" || fail "mcp: tool call on unicode path"
else
    skip "mcp stress" "npx not installed"
fi

# ── Cowork patcher against broken inputs ─────────────────────────────────────
orig=/app/extra/claude-desktop-orig/resources/app.asar
/usr/bin/python3 - "$orig" "$T" <<'PY'
import sys, shutil
src, t = sys.argv[1], sys.argv[2]
data = open(src, "rb").read()
open(t + "/missing.asar", "wb").write(data.replace(b"/usr/share/OVMF/", b"/opt/share/OVMF/"))
open(t + "/truncated.asar", "wb").write(data[:1000])
open(t + "/garbage.asar", "wb").write(b"\x00" * 5000)
PY
for case in missing truncated garbage; do
    out=$(cowork-patch "$T/$case.asar" "$T/$case.out" 2>&1); rc=$?
    if [ $rc -ne 0 ] && [ ! -e "$T/$case.out" ] && echo "$out" | grep -q '^disabled'; then
        pass "patcher: refuses $case archive safely ($(echo "$out" | tail -1 | cut -c1-60))"
    else
        fail "patcher: $case archive" "rc=$rc out=$out"
    fi
done
cowork-patch "$orig" "$T/good.out" >/dev/null && cmp -s "$T/good.out" /app/extra/claude-desktop/resources/app.asar \
    && pass "patcher: output is identical to the installed patched file" || fail "patcher: reproducible output"

# ── Unpacker against a corrupt download ──────────────────────────────────────
mkdir "$T/extra"; head -c 5000000 /dev/urandom > "$T/extra/claude-desktop.deb"
(cd "$T/extra" && sh /app/bin/apply_extra >/dev/null 2>&1); rc=$?
[ $rc -ne 0 ] && [ ! -e "$T/extra/claude-desktop" ] && pass "install: corrupt .deb makes the install fail cleanly (no half app)" \
    || fail "install: corrupt .deb" "rc=$rc"
