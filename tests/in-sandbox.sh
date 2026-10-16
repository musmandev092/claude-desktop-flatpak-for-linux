#!/bin/bash
# Checks that run INSIDE the Flatpak sandbox. Started by tests/run-tests.sh.
# Prints one line per check: PASS / FAIL / SKIP.
set -u
cd "$HOME" || exit 1

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1${2:+  — $2}"; }
skip() { echo "SKIP  $1${2:+  — $2}"; }
is() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1" "expected [$3] got [$2]"; fi; }
check() { local name=$1; shift; if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi; }

EXTRA=/app/extra
export HOST_BIN="$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-bin"

# ── Installation ─────────────────────────────────────────────────────────────
check "install: Claude binary present"          test -x $EXTRA/claude-desktop/claude-desktop
check "install: Claude version recorded"        test -s $EXTRA/claude-version
check "install: no local VM stack bundled"     test ! -e /app/bin/qemu-system-x86_64

# ── Plugin bridge ────────────────────────────────────────────────────────────
if host-bridge link; then
    pass "bridge: $(ls "$HOST_BIN" | wc -l) host commands linked"
else
    fail "bridge: host-bridge link"
fi
export PATH="/app/bin:$HOST_BIN:$PATH"

has() { [ -e "$HOST_BIN/$1" ]; }
for c in bash git python3 node npx uvx; do
    if has "$c"; then pass "bridge: '$c' comes from the host/toolbox"; else skip "bridge: '$c'" "not installed on host/toolbox"; fi
done

check "bridge: exit code passes through" bash -c '[ "$(bash -c "exit 7"; echo $?)" = 7 ]'
[ "$(echo hello | python3 -c 'import sys; print(sys.stdin.read().strip())')" = hello ] \
    && pass "bridge: stdin passes through" || fail "bridge: stdin passes through"
# The REAL working directory (getcwd), not $PWD: node/uv crash if it's unreachable
[ "$(cd "$HOME" && python3 -c 'import os; print(os.getcwd())' 2>&1)" = "$HOME" ] \
    && pass "bridge: working directory is real (getcwd)" || fail "bridge: working directory (getcwd)"
[ "$(MY_TEST_VAR=42 python3 -c 'import os; print(os.environ.get("MY_TEST_VAR"))')" = 42 ] \
    && pass "bridge: environment variables pass through" || fail "bridge: environment variables pass through"
[ "$(env -i HOME="$HOME" "$HOST_BIN/bash" -lc 'echo ok' 2>/dev/null)" = ok ] \
    && pass "bridge: login shell works from an empty environment" || fail "bridge: login shell from an empty environment"
if grep -qE '^[[:space:]]*TOOLBOX=[^[:space:]]' "$HOME/.config/claude-desktop-flatpak/settings.conf" 2>/dev/null; then
    host-run true </dev/null >/dev/null 2>&1          # first call finds the toolbox
    s=$(date +%s%N); out=$(host-run echo ok </dev/null 2>&1); ms=$(( ($(date +%s%N) - s) / 1000000 ))
    [ "$out" = ok ] && [ "$ms" -lt 150 ] && pass "speed: a toolbox command takes ${ms} ms (fast path)" \
        || fail "speed: toolbox command" "${ms} ms (fast path not used?)"
fi
out=$(script -qec 'bash -c "tty"' /dev/null 2>/dev/null | tr -d '\r\0')
case "$out" in *"/dev/pts/"*) pass "bridge: terminal gets a real pty";; *) fail "bridge: terminal gets a real pty" "$out";; esac

# Electron gives plugins SOCKETS as stdin/stdout (not pipes). Bash reads
# ~/.bashrc when stdin is a socket, so banners there must not leak into the
# plugin's output. Checked with a socket pair, exactly like the app does it.
sock_out=$(/usr/bin/python3 -c '
import socket, subprocess
a, b = socket.socketpair(); c, d = socket.socketpair()
p = subprocess.Popen(["python3", "-c", "import sys; print(sys.stdin.readline().strip())"],
                     stdin=b.fileno(), stdout=d.fileno(), stderr=subprocess.DEVNULL)
b.close(); d.close(); a.sendall(b"CLEAN-LINE\n"); c.settimeout(60)
out = b""
while True:
    chunk = c.recv(4096)
    if not chunk: break
    out += chunk
print(out.decode(errors="replace").strip()); p.wait()')
is "bridge: socket stdio stays clean (no shell banners)" "$sock_out" "CLEAN-LINE"

mcp_init='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}'
mcp() { { echo "$mcp_init"; sleep "$1"; } | timeout 180 "${@:2}" 2>/dev/null | head -c 400; }
if has npx; then
    mcp 10 npx -y @modelcontextprotocol/server-filesystem "$HOME" | grep -q '"serverInfo"' \
        && pass "mcp: npx server (filesystem) answers" || fail "mcp: npx server (filesystem)"
else skip "mcp: npx server" "npx not installed"; fi
if has uvx; then
    mcp 20 uvx mcp-server-time | grep -q '"serverInfo"' \
        && pass "mcp: uvx server (time) answers" || fail "mcp: uvx server (time)"
else skip "mcp: uvx server" "uvx not installed"; fi
