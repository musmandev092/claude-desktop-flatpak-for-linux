#!/bin/sh
# Launcher: runs every time the user opens the app.

# Private temp folder for this app. It also exists outside the sandbox
# (/run/user/<uid>/app/<id>), so host tools can read files Claude puts there.
export TMPDIR="$XDG_RUNTIME_DIR/app/$FLATPAK_ID"

# X11-only desktops (or Wayland not shared with us): tell Electron to use X11,
# otherwise it tries Wayland because of XDG_SESSION_TYPE and fails to start
if [ ! -S "$XDG_RUNTIME_DIR/${WAYLAND_DISPLAY:-wayland-0}" ]; then
    unset WAYLAND_DISPLAY
    set -- --ozone-platform=x11 "$@"
fi

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

# zypak lets Chromium's own sandbox work inside the Flatpak sandbox.
# Cowork runs in Anthropic's cloud; Claude reaches the folders you connect
# through this app, so nothing extra is needed here.
exec zypak-wrapper /app/extra/claude-desktop/claude-desktop "$@"
