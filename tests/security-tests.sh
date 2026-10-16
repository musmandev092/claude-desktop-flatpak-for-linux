#!/bin/bash
# Security tests against the INSTALLED Flatpak (Claude may stay open):
#     tests/security-tests.sh            the installed app
#     tests/security-tests.sh --project  scripts/ in this folder
# Also checks that the published repository only accepts its real signing key.
set -u
APP_ID=io.github.musmandev092.ClaudeDesktop
HERE=$(cd "$(dirname "$0")" && pwd)
PAGES=https://musmandev092.github.io/claude-desktop-flatpak-for-linux
env=()
[ "${1:-}" = --project ] && env=(--env=PROJECT=1)
out=$(flatpak run --command=bash "${env[@]}" "$APP_ID" "$HERE/security-in-sandbox.sh" 2>&1)

# The published repository must refuse a wrong signing key and unsigned access
t=$(mktemp -d)
# (gpg starts a gpg-agent for the throwaway key: stop it, or it keeps our output open)
trap 'gpgconf --homedir "$t/g" --kill gpg-agent 2>/dev/null; rm -rf "$t"' EXIT
mkdir -m 700 "$t/g"
gpg --homedir "$t/g" --batch --pinentry-mode loopback --passphrase '' \
    --quick-gen-key "wrong key <wrong@example.invalid>" ed25519 sign never >/dev/null 2>&1
gpg --homedir "$t/g" --export > "$t/wrong.gpg" 2>/dev/null
if [ ! -s "$t/wrong.gpg" ]; then
    out+=$'\n'"FAIL  could not create the throwaway key for the wrong-key test"
fi
FLATPAK_USER_DIR="$t/fp" flatpak --user remote-add --gpg-import="$t/wrong.gpg" wrongkey "$PAGES/repo/" 2>/dev/null
if [ ! -s "$t/wrong.gpg" ]; then
    :   # reported above
elif FLATPAK_USER_DIR="$t/fp" flatpak --user remote-ls wrongkey >/dev/null 2>&1; then
    out+=$'\n'"FAIL  published repo accepted a WRONG signing key"
else
    out+=$'\n'"PASS  published repo rejects a wrong signing key"
fi
FLATPAK_USER_DIR="$t/fp" flatpak --user remote-add --from rightkey "$PAGES/claude-desktop.flatpakrepo" 2>/dev/null
if FLATPAK_USER_DIR="$t/fp" flatpak --user remote-ls rightkey 2>/dev/null | grep -q "$APP_ID"; then
    out+=$'\n'"PASS  published repo verifies with the real key"
else
    out+=$'\n'"FAIL  published repo does not verify with the real key"
fi
echo "$out"
p=$(grep -c '^PASS' <<<"$out"); f=$(grep -c '^FAIL' <<<"$out")
echo; echo "Result: $p passed, $f failed"
[ "$f" -eq 0 ]
