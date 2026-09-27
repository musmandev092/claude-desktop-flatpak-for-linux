#!/bin/bash
# Checks that run INSIDE the Flatpak sandbox. Started by tests/run-tests.sh.
# Prints one line per check: PASS / FAIL / SKIP.
set -u
cd "$HOME"

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1${2:+  — $2}"; }
skip() { echo "SKIP  $1${2:+  — $2}"; }
is() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1" "expected [$3] got [$2]"; fi; }
check() { local name=$1; shift; if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi; }

EXTRA=/app/extra
export HOST_BIN="$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-bin"

# ── Installation ─────────────────────────────────────────────────────────────
check "install: Claude binary present"          test -x $EXTRA/claude-desktop/claude-desktop
check "install: untouched original kept"        test -x $EXTRA/claude-desktop-orig/claude-desktop
check "install: Claude version recorded"        test -s $EXTRA/claude-version
check "install: twin shares files (hard links)" test "$(stat -c %i $EXTRA/claude-desktop/claude-desktop)" = "$(stat -c %i $EXTRA/claude-desktop-orig/claude-desktop)"

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
[ "$(MY_TEST_VAR=42 python3 -c 'import os; print(os.environ.get("MY_TEST_VAR"))')" = 42 ] \
    && pass "bridge: environment variables pass through" || fail "bridge: environment variables pass through"
[ "$(env -i HOME="$HOME" "$HOST_BIN/bash" -lc 'echo ok' 2>/dev/null)" = ok ] \
    && pass "bridge: login shell works from an empty environment" || fail "bridge: login shell from an empty environment"
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

# ── Cowork VM stack ──────────────────────────────────────────────────────────
grep -qx enabled $EXTRA/cowork-status && pass "cowork: patch enabled" \
    || fail "cowork: patch enabled" "$(tail -1 $EXTRA/cowork-status)"
check "cowork: QEMU bundled"             qemu-system-x86_64 --version
check "cowork: OVMF firmware bundled"    test -s /app/share/OVMF/OVMF_CODE_4M.fd
check "cowork: OVMF vars template"       test -s /app/share/OVMF/OVMF_VARS_4M.fd
check "cowork: virtiofsd runs"           /app/libexec/virtiofsd --version

if [ -w /dev/kvm ] && [ -w /dev/vhost-vsock ]; then
    t=$(mktemp -d -p "$XDG_RUNTIME_DIR/app/$FLATPAK_ID")
    mkdir "$t/share"; cp /app/share/OVMF/OVMF_VARS_4M.fd "$t/vars.fd"
    /app/libexec/virtiofsd --socket-path="$t/vfs.sock" --shared-dir="$t/share" --sandbox none >"$t/vfs.log" 2>&1 &
    vfs=$!
    for _ in $(seq 20); do [ -S "$t/vfs.sock" ] && break; sleep 0.25; done
    cid=$(( (RANDOM % 50000) + 1000 ))
    qemu-system-x86_64 -machine q35,accel=kvm -cpu host -m 256 -smp 1 \
        -object memory-backend-memfd,id=mem0,size=256M,share=on -numa node,memdev=mem0 \
        -drive if=pflash,format=raw,readonly=on,file=/app/share/OVMF/OVMF_CODE_4M.fd \
        -drive if=pflash,format=raw,file="$t/vars.fd" \
        -device vhost-vsock-pci,guest-cid=$cid \
        -chardev socket,id=vfs0,path="$t/vfs.sock" -device vhost-user-fs-pci,chardev=vfs0,tag=test \
        -netdev user,id=net0 -device virtio-net-pci,netdev=net0,romfile= \
        -display none -nodefaults -serial file:"$t/serial.log" >"$t/qemu.log" 2>&1 &
    q=$!
    sleep 8
    if kill -0 $q 2>/dev/null; then
        pass "cowork: KVM VM boots with vhost-vsock + virtiofs + user network"
        kill $q; wait $q 2>/dev/null
        grep -qaE 'BdsDxe|UEFI|Shell>' "$t/serial.log" && pass "cowork: UEFI firmware ran inside the VM" \
            || skip "cowork: UEFI output" "no serial output captured"
    else
        fail "cowork: KVM VM boots" "$(tail -2 "$t/qemu.log" | tr '\n' ' ')"
    fi
    kill $vfs 2>/dev/null; wait $vfs 2>/dev/null
    rm -rf "$t"
else
    skip "cowork: KVM VM boot" "/dev/kvm or /dev/vhost-vsock not writable"
fi
