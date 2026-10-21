#!/bin/bash
#
# test-install.sh - install-test the claude-desktop RPM in a clean Fedora
# container, as root. Real download from downloads.claude.ai; nothing faked.
#
# Usage: tests/test-install.sh path/to/claude-desktop-*.x86_64.rpm
set -euo pipefail

RPM="${1:?usage: $0 claude-desktop-*.x86_64.rpm}"
APP=/usr/lib/claude-desktop
step() { printf '\n=== %s\n' "$*"; }
fail() { printf 'TEST FAILED: %s\n' "$*" >&2; exit 1; }

step "install (weak deps off, like a minimal system)"
dnf -y -q --setopt=install_weak_deps=False install "$RPM" desktop-file-utils
VERSION=$(rpm -q --qf '%{VERSION}' claude-desktop)

step "the official build is in place and verified"
[ "$(cat /var/lib/claude-desktop-rpm/installed-version)" = "$VERSION" ] || fail "installed-version is not $VERSION"
[ ! -e /var/lib/claude-desktop-rpm/pending ] || fail "fetch left a pending marker"
claude-desktop-verify
[ "$(stat -c '%a %U' "$APP/chrome-sandbox")" = "4755 root" ] || fail "chrome-sandbox is not setuid root"
[ "$(readlink -f /usr/bin/claude-desktop)" = "$APP/claude-desktop" ] || fail "launcher link is wrong"
rpm -qf "$APP/resources/app.asar" | grep -q '^claude-desktop-' || fail "rpm does not own the app files"
rpm -V claude-desktop || fail "rpm -V reports changes in our own files"

step "libraries: nothing missing"
missing=$(for f in "$APP/claude-desktop" "$APP/chrome-sandbox" $(find "$APP/resources/app.asar.unpacked" -name '*.node'); do
              ldd "$f" | grep 'not found' | sed "s|^|$f: |"; done || true)
[ -z "$missing" ] || fail "missing libraries: $missing"

step "desktop integration (what the .deb's postinst does)"
desktop-file-validate /usr/share/applications/com.anthropic.Claude.desktop
[ -f /usr/share/mime/packages/com.anthropic.Claude.xml ] || fail "MIME types not installed"
grep -q 'vnd.anthropic.mcpb' /usr/share/mime/mime.cache 2>/dev/null \
    || grep -rq 'vnd.anthropic.mcpb' /usr/share/mime/application/ || fail "MIME database not refreshed"
ls /usr/share/icons/hicolor/*/apps/claude-desktop.png >/dev/null || fail "icons missing"

step "tamper detection and repair"
printf 'x' >> "$APP/resources/app.asar"
if claude-desktop-verify >/dev/null 2>&1; then fail "verify did not notice a changed file"; fi
claude-desktop-fetch
claude-desktop-verify

step "offline install: retry is armed, nothing half-installed"
# Break the network for curl only, then run fetch as the retry service would.
echo 'proxy = "http://127.0.0.1:9"' > /root/.curlrc
if claude-desktop-fetch >/dev/null 2>&1; then fail "fetch claimed success offline"; fi
[ -e /var/lib/claude-desktop-rpm/pending ] || fail "no pending marker after a failed download"
[ -L /etc/systemd/system/multi-user.target.wants/claude-desktop-fetch.service ] || fail "retry service not enabled"
rm -f /root/.curlrc
claude-desktop-fetch --if-pending
[ ! -e /var/lib/claude-desktop-rpm/pending ] || fail "pending marker not cleared"
[ ! -e /etc/systemd/system/multi-user.target.wants/claude-desktop-fetch.service ] || fail "retry service still enabled"
claude-desktop-verify

step "remove: nothing left behind"
dnf -y -q remove claude-desktop
for p in "$APP" /usr/bin/claude-desktop /usr/share/applications/com.anthropic.Claude.desktop \
         /usr/share/mime/packages/com.anthropic.Claude.xml /usr/share/doc/claude-desktop \
         /var/lib/claude-desktop-rpm /var/cache/claude-desktop-rpm /usr/share/claude-desktop-rpm; do
    [ ! -e "$p" ] || fail "left behind: $p"
done
left=$(find / -xdev \( -name '*claude-desktop*' -o -name 'com.anthropic.Claude*' \) -not -path '/proc/*' \
            -not -path '/tmp/*' -not -path "${GITHUB_WORKSPACE:-/nonexistent}/*" \
            -not -path "$(dirname "$(readlink -f "$RPM")")/*" 2>/dev/null || true)
[ -z "$left" ] || fail "left behind: $left"

printf '\nALL TESTS PASSED (Claude Desktop %s)\n' "$VERSION"
