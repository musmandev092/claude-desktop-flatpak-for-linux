#!/bin/bash
# Security checks that run INSIDE the sandbox. Started by tests/security-tests.sh.
# They try to break the bridge's promises: no code runs from environment
# variables or arguments, API keys in job files stay private and are never left
# behind, toolbox names cannot select another container, and a user's
# ~/.bashrc cannot leak into a plugin's output.
HR=/app/bin/host-run; [ -n "${PROJECT:-}" ] && HR="/bin/bash $HOME/Projects/claude-desktop-flatpak-for-linux/scripts/host-run"
R=$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-run
pass(){ echo "PASS  $1"; }; fail(){ echo "FAIL  $1 ${2:-}"; }
for mode in --host "--toolbox dev"; do
  # 1. shellshock: a function smuggled in through the environment must not exist on the other side
  out=$(env 'BASH_FUNC_evil%%=() { echo PWNED; }' $HR $mode bash -c 'type evil 2>&1; echo done' 2>&1)
  case "$out" in *PWNED*|*"is a function"*) fail "shellshock function blocked ($mode)" "$out";; *) pass "shellshock function blocked ($mode)";; esac
  # 2. shellshock-style value is passed as plain text and never executed
  out=$(EVIL='() { :; }; echo PWNED' $HR $mode bash -c 'printf %s "$EVIL"' 2>&1)
  [ "$out" = '() { :; }; echo PWNED' ] && pass "shellshock value stays text ($mode)" || fail "shellshock value ($mode)" "$out"
  # 3. command substitution in args/env is never run by the bridge
  out=$($HR $mode printf '%s|%s' '$(touch $HOME/.var/app/$FLATPAK_ID/cache/pwned-arg)' "`echo x`" 2>&1)
  [ "$out" = '$(touch $HOME/.var/app/$FLATPAK_ID/cache/pwned-arg)|x' ] && pass "no shell evaluation of arguments ($mode)" || fail "arguments evaluated ($mode)" "$out"
done
# 4. job files (they carry API keys) are private while a command runs
SECRET_TOKEN=abc $HR --toolbox dev sleep 3 </dev/null & sleep 1
perm=$(stat -c %a "$R"); [ "$perm" = 700 ] && pass "job folder is private (700)" || fail "job folder permissions" "$perm"
bad=$(find "$R" -name 'job.*' -perm /077 | wc -l); [ "$bad" = 0 ] && pass "no job file readable by others" || fail "job files readable by others" "$bad"
wait
# 5. a loosened job folder is tightened again on next use
chmod 755 "$R"; $HR --host true; perm=$(stat -c %a "$R")
[ "$perm" = 700 ] && pass "loosened job folder is re-secured" || fail "job folder stays open" "$perm"
# 6. nothing left behind that could hold secrets
sleep 1; left=$(find "$R" -name 'job.*' | wc -l); [ "$left" = 0 ] && pass "no job files left after commands" || fail "job files left" "$left"
# 7. toolbox names cannot be used to pick another container
for name in --latest -l '$(id)' '../dev' 'dev;id'; do
  $HR --toolbox "$name" true 2>/dev/null; rc=$?
  [ "$rc" = 125 ] && pass "toolbox name '$name' rejected" || fail "toolbox name '$name'" "rc=$rc"
done
# 8. a plugin that is itself `bash -c`, with a socket as stdin (like Claude gives it),
#    must not print the user's ~/.bashrc banner into its output
fake=$HOME/.var/app/$FLATPAK_ID/cache/fake-home; mkdir -p "$fake"; echo 'echo BANNER-FROM-BASHRC' > "$fake/.bashrc"
for mode in --host "--toolbox dev"; do
  out=$(HOME_FAKE=$fake MODE="$mode" HRCMD="$HR" /usr/bin/python3 -c '
import os, socket, subprocess, shlex
a, b = socket.socketpair()
env = dict(os.environ, HOME=os.environ["HOME_FAKE"])
p = subprocess.Popen(shlex.split(os.environ["HRCMD"]) + shlex.split(os.environ["MODE"]) +
                     ["bash", "-c", "read l; echo \"got:$l\""], stdin=b.fileno(),
                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
b.close(); a.sendall(b"hello\n"); a.shutdown(socket.SHUT_WR)
print(p.communicate(timeout=60)[0].decode().strip())')
  [ "$out" = "got:hello" ] && pass "bash plugin on a socket stays clean ($mode)" || fail "bashrc banner leaked ($mode)" "$out"
done
rm -rf "$fake"
# 9. nothing was created by the injected arguments above
[ -e "$HOME/.var/app/$FLATPAK_ID/cache/pwned-arg" ] && fail "an injected argument created a file" || pass "injected arguments created nothing"
