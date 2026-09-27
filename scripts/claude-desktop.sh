#!/bin/sh
# Launcher: runs every time the user opens the app.

SETTINGS="$HOME/.config/claude-desktop-flatpak/settings.conf"

# Private temp folder for this app. It also exists outside the sandbox
# (/run/user/<uid>/app/<id>), so host tools can read files Claude puts there.
export TMPDIR="$XDG_RUNTIME_DIR/app/$FLATPAK_ID"

# Tell Electron our desktop file name, so GNOME shows our icon on the window
export CHROME_DESKTOP="$FLATPAK_ID.desktop"

# ── Plugin bridge ────────────────────────────────────────────────────────────
# Link every host/toolbox command into HOST_BIN, then put it on PATH before the
# sandbox's own tools. The list is refreshed in the background for the next
# launch, so newly installed tools show up after a restart.
export HOST_BIN="$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-bin"
if host-bridge link; then
    export PATH="/app/bin:$HOST_BIN:$PATH"
    # Claude Code and the built-in terminal use your real shell
    [ -e "$HOST_BIN/bash" ] && export SHELL="$HOST_BIN/bash"
    (host-bridge scan >/dev/null 2>&1 &)
fi

# ── Cowork: run the patched twin, or the untouched original ──────────────────
version=$(cat /app/extra/claude-version 2>/dev/null)
broken=/var/data/cowork-broken        # holds the Claude version that failed to start
APP=/app/extra/claude-desktop
if grep -qx 'COWORK=off' "$SETTINGS" 2>/dev/null || [ "$(cat "$broken" 2>/dev/null)" = "$version" ]; then
    APP=/app/extra/claude-desktop-orig
fi

# zypak lets Chromium's own sandbox work inside the Flatpak sandbox
start=$(date +%s)
zypak-wrapper "$APP/claude-desktop" "$@"
rc=$?

# Safety net: if the patched app crashed right away, remember it for this
# version and start the original instead (Cowork off, everything else works).
if [ "$rc" -ne 0 ] && [ "$APP" = /app/extra/claude-desktop ] && [ $(( $(date +%s) - start )) -lt 15 ]; then
    echo "$version" > "$broken"
    echo "claude-desktop: patched app failed to start (exit $rc); Cowork disabled for $version" >&2
    exec zypak-wrapper /app/extra/claude-desktop-orig/claude-desktop "$@"
fi
exit "$rc"
