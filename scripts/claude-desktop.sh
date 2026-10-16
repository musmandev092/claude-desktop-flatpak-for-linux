#!/bin/sh

export TMPDIR="$XDG_RUNTIME_DIR/app/$FLATPAK_ID"

if [ -S "$XDG_RUNTIME_DIR/${WAYLAND_DISPLAY:-wayland-0}" ]; then
    set -- --ozone-platform=wayland "$@"
else
    unset WAYLAND_DISPLAY
    set -- --ozone-platform=x11 "$@"
fi

export CHROME_DESKTOP="$FLATPAK_ID.desktop"

export HOST_BIN="$XDG_RUNTIME_DIR/app/$FLATPAK_ID/host-bin"
if host-bridge link; then
    export PATH="/app/bin:$HOST_BIN:$PATH"
    s=$(host-bridge shell) && export SHELL="$s"
fi

env -0 > "$TMPDIR/sandbox.env"

exec zypak-wrapper /app/extra/claude-desktop/claude-desktop "$@"

