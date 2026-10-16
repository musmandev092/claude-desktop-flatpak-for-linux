#!/bin/bash
HR=/app/bin/host-run; [ -n "${PROJECT:-}" ] && HR="/bin/bash $(cd "$(dirname "$0")/.." && pwd)/scripts/host-run"
R=$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-run
pass(){ echo "PASS  $1"; }; fail(){ echo "FAIL  $1 ${2:-}"; }
jobs_now() { find "$R" -maxdepth 1 -name 'job.*' -printf '%f\n' 2>/dev/null | sort; }
pre=$(jobs_now)
newjobs() { comm -13 <(echo "$pre") <(jobs_now) | grep -c .; }
mode=host
out=$(env 'BASH_FUNC_evil%%=() { echo PWNED; }' $HR bash -c 'type evil 2>&1; echo done' 2>&1)
case "$out" in *PWNED*|*"is a function"*) fail "shellshock function blocked ($mode)" "$out";; *) pass "shellshock function blocked ($mode)";; esac
out=$(EVIL='() { :; }; echo PWNED' $HR bash -c 'printf %s "$EVIL"' 2>&1)
[ "$out" = '() { :; }; echo PWNED' ] && pass "shellshock value stays text ($mode)" || fail "shellshock value ($mode)" "$out"
out=$($HR printf '%s|%s' '$(touch $HOME/.var/app/$FLATPAK_ID/cache/pwned-arg)' "`echo x`" 2>&1)
[ "$out" = '$(touch $HOME/.var/app/$FLATPAK_ID/cache/pwned-arg)|x' ] && pass "no shell evaluation of arguments ($mode)" || fail "arguments evaluated ($mode)" "$out"
SECRET_TOKEN=abc $HR sleep 3 </dev/null & sleep 1
perm=$(stat -c %a "$R"); [ "$perm" = 700 ] && pass "job folder is private (700)" || fail "job folder permissions" "$perm"
n=$(newjobs); [ "$n" = 0 ] && pass "a running plugin's environment is never written to a file" || fail "job files for a running plugin" "$n"
wait
chmod 755 "$R"; $HR true; perm=$(stat -c %a "$R")
[ "$perm" = 700 ] && pass "loosened job folder is re-secured" || fail "job folder stays open" "$perm"
sleep 1; left=$(newjobs); [ "$left" = 0 ] && pass "no job files left after commands" || fail "job files left" "$left"
for i in $(seq 50); do KEY=x$i $HR /usr/bin/true </dev/null >/dev/null 2>&1 & p=$!; sleep 0.0$((RANDOM % 9)); kill -9 $p 2>/dev/null; done 2>/dev/null; wait 2>/dev/null
sleep 1; left=$(newjobs); [ "$left" = 0 ] && pass "commands killed while starting leave nothing behind" || fail "killed commands left job files" "$left"
fake=$HOME/.var/app/$FLATPAK_ID/cache/fake-home; mkdir -p "$fake"; echo 'echo BANNER-FROM-BASHRC' > "$fake/.bashrc"
out=$(HOME_FAKE=$fake HRCMD="$HR" /usr/bin/python3 -c '
import os, socket, subprocess, shlex
a, b = socket.socketpair()
env = dict(os.environ, HOME=os.environ["HOME_FAKE"])
p = subprocess.Popen(shlex.split(os.environ["HRCMD"]) +
                   ["bash", "-c", "read l; echo \"got:$l\""], stdin=b.fileno(),
                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
b.close(); a.sendall(b"hello\n"); a.shutdown(socket.SHUT_WR)
print(p.communicate(timeout=60)[0].decode().strip())')
[ "$out" = "got:hello" ] && pass "bash plugin on a socket stays clean ($mode)" || fail "bashrc banner leaked ($mode)" "$out"
printf '%s\n' 'echo BANNER-FROM-BASHRC' 'read -t 3 _' > "$fake/.bashrc"
out=$(HOME_FAKE=$fake HRCMD="$HR" /usr/bin/python3 -c '
import os, socket, subprocess, shlex, time
def mine(): return {p for p in os.listdir("/proc") if p.isdigit()}
before = mine()
a, b = socket.socketpair()
env = dict(os.environ, HOME=os.environ["HOME_FAKE"])
p = subprocess.Popen(shlex.split(os.environ["HRCMD"]) + ["bash", "-c", "read l; echo \"got:$l\""],
                     stdin=b.fileno(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
b.close(); a.sendall(b"hello\n")
out = p.communicate(timeout=60)[0].decode().strip()
time.sleep(1)
left = [p for p in mine() - before if os.path.exists(f"/proc/{p}/cmdline")]
print(out if not left else f"{out} + {len(left)} process(es) left running")
a.close()')
[ "$out" = "got:hello" ] && pass "long-running bash plugin on a socket: clean, nothing left ($mode)" \
    || fail "long-running bash plugin on a socket ($mode)" "$out"
rm -rf "$fake"
[ -e "$HOME/.var/app/$FLATPAK_ID/cache/pwned-arg" ] && fail "an injected argument created a file" || pass "injected arguments created nothing"

