#!/bin/bash
set -u
cd "$HOME" || exit 1

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1${2:+  — $2}"; }
skip() { echo "SKIP  $1${2:+  — $2}"; }
is() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1" "expected [$3] got [$2]"; fi; }
check() { local name=$1; shift; if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi; }

EXTRA=/app/extra
export HOST_BIN="$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-bin"
export PATH="/app/bridge/bin:$PATH"

check "install: Claude binary present"          test -x $EXTRA/claude-desktop/claude-desktop
check "install: Claude version recorded"        test -s $EXTRA/claude-version
check "install: no local VM stack bundled"     test ! -e /app/bin/qemu-system-x86_64
check "install: window app ID matches the desktop file" \
    grep -aqF "\"desktopName\":\"$FLATPAK_ID.desktop\"" $EXTRA/claude-desktop/resources/app.asar

if host-bridge link; then
    pass "bridge: $(ls "$HOST_BIN" | wc -l) host commands linked"
else
    fail "bridge: host-bridge link"
fi
fake=$(mktemp -d -p "$HOME/.cache" startup-test.XXXXXX)
mkdir -p "$fake/bin" && printf '#!/bin/sh\n' > "$fake/bin/startup-test-tool" && chmod +x "$fake/bin/startup-test-tool"
startup() { for f in .bash_profile .zprofile; do printf '%s\n' "$@" > "$fake/$f"; done; }
scan() { HOME=$fake XDG_CACHE_HOME=$fake/cache host-bridge scan && grep -qx "$1" "$fake/cache/host-bridge/host.commands"; }
startup 'for i in 1 2 3 4 5 6 7 8; do printf "\033[1;34m  OS:\033[0m Fedora %s\n" "$i"; done' \
        'echo "warning: banner" >&2' '(sleep 5; echo late) &' 'read -r _' "export PATH=\"$fake/bin:\$PATH\""
s=$(date +%s)
if scan startup-test-tool && [ $(( $(date +%s) - s )) -lt 10 ]; then
    pass "bridge: startup files with a banner or a prompt"
else
    fail "bridge: startup files with a banner or a prompt"
fi
startup 'echo "Welcome banner"' 'exit 1'
check "bridge: startup files that exit early" scan ls
fenv=(env HOME="$fake" XDG_CACHE_HOME="$fake/cache" HOST_BIN="$fake/hb")
"${fenv[@]}" host-bridge link
( "${fenv[@]}" host-bridge watch & sleep 30 ) & wpid=$!
sleep 2; printf '#!/bin/sh\n' > "$fake/bin/late-tool" && chmod +x "$fake/bin/late-tool"
until [ -e "$fake/hb/late-tool" ] || ! kill -0 $wpid 2>/dev/null; do sleep 0.5; done
check "bridge: commands installed after start get a wrapper" test -e "$fake/hb/late-tool"
kill $wpid 2>/dev/null; wait $wpid 2>/dev/null
rm -rf "$fake"

export PATH="/app/bridge/bin:/app/bin:$HOST_BIN:$PATH"
has() { [ -e "$HOST_BIN/$1" ]; }
for c in bash git python3 node npx uvx toolbox podman flatpak rpm-ostree; do
    if has "$c"; then pass "bridge: '$c' comes from the host"; else skip "bridge: '$c'" "not installed on the host"; fi
done
if has toolbox; then check "bridge: Claude can call the host's toolbox" toolbox --version; fi
if has flatpak; then check "bridge: Claude can call the host's flatpak" sh -c "flatpak list --app --columns=application | grep -qx '$FLATPAK_ID'"; fi

check "bridge: exit code passes through" bash -c '[ "$(bash -c "exit 7"; echo $?)" = 7 ]'
[ "$(echo hello | python3 -c 'import sys; print(sys.stdin.read().strip())')" = hello ] \
    && pass "bridge: stdin passes through" || fail "bridge: stdin passes through"
[ "$(cd "$HOME" && python3 -c 'import os; print(os.getcwd())' 2>&1)" = "$HOME" ] \
    && pass "bridge: working directory is real (getcwd)" || fail "bridge: working directory (getcwd)"
[ "$(MY_TEST_VAR=42 python3 -c 'import os; print(os.environ.get("MY_TEST_VAR"))')" = 42 ] \
    && pass "bridge: environment variables pass through" || fail "bridge: environment variables pass through"
[ -e "$XDG_RUNTIME_DIR/app/$FLATPAK_ID/sandbox.env" ] || env -0 > "$XDG_RUNTIME_DIR/app/$FLATPAK_ID/sandbox.env"
is "bridge: MCP env vars pass (PYTHONPATH, NODE_PATH)" \
   "$(PYTHONPATH=/t/py NODE_PATH=/t/node python3 -c 'import os; print(os.environ.get("PYTHONPATH"), os.environ.get("NODE_PATH"))')" "/t/py /t/node"
is "bridge: sandbox-only variables stay inside" \
   "$(python3 -c 'import os; print(os.environ.get("PYTHONUSERBASE"), os.environ.get("ALSA_CONFIG_PATH"))')" "None None"
[ "$(env -i HOME="$HOME" "$HOST_BIN/bash" -lc 'echo ok' 2>/dev/null | tail -n 1)" = ok ] \
    && pass "bridge: login shell works from an empty environment" || fail "bridge: login shell from an empty environment"
host-run true </dev/null >/dev/null 2>&1
s=$(date +%s%N); out=$(host-run echo ok </dev/null 2>&1); ms=$(( ($(date +%s%N) - s) / 1000000 ))
[ "$out" = ok ] && pass "speed: a host command takes ${ms} ms" || fail "speed: host command" "$out"
out=$(script -qec 'bash -c "test -t 0 && readlink /proc/self/fd/0"' /dev/null 2>/dev/null | tr -d '\r\0')
case "$out" in *"/dev/pts/"*) pass "bridge: terminal gets a real pty";; *) fail "bridge: terminal gets a real pty" "$out";; esac
# The pty must be one the host can resolve (#10): tty, ttyname and GPG_TTY work.
out=$(script -qec 'bash -c "host-run sh -c '"'"'t=\$(tty) && test -e \"\$t\" && python3 -c \"import os; os.ttyname(0)\" && echo HOSTTTY'"'"'"' /dev/null 2>&1 | tr -d '\r\0')
case "$out" in *HOSTTTY*) pass "bridge: terminal pty resolves on the host";; *) fail "bridge: terminal pty resolves on the host" "$out";; esac
out=$(script -qec 'bash -c "stty cols 101 rows 33; host-run stty size"' /dev/null 2>&1 | tr -d '\r\0')
case "$out" in *"33 101"*) pass "bridge: terminal size reaches the host";; *) fail "bridge: terminal size reaches the host" "$out";; esac
out=$(script -qec 'bash -c "host-run sh -c '"'"'exit 7'"'"'; echo rc=\$?"' /dev/null 2>&1 | tr -d '\r\0')
case "$out" in *rc=7*) pass "bridge: terminal exit status comes back";; *) fail "bridge: terminal exit status comes back" "$out";; esac

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
eof_out=$(/usr/bin/python3 -c '
import socket, subprocess, tempfile
a, b = socket.socketpair()
with tempfile.TemporaryFile("w+") as f:
    subprocess.run(["bash", "-c", "read x; echo rc=$?"], stdin=b.fileno(), stdout=f, timeout=20)
    f.seek(0); print(f.read().strip())' 2>&1)
is "bridge: unwritten socket stdin gets EOF (Bash tool heredocs)" "$eof_out" "rc=1"

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

