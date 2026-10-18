#!/bin/sh
# Lives in the app and should never need to change: any change here makes every
# user download Claude's .deb again. Put launcher logic in scripts/bridge-launch.

[ -x /app/bridge/bin/bridge-launch ] && exec /app/bridge/bin/bridge-launch "$@"

echo "claude-desktop: Bridge extension missing, Claude Code can't use host tools" >&2
echo "  fix: flatpak install io.github.musmandev092.ClaudeDesktop.Bridge" >&2
export TMPDIR="$XDG_RUNTIME_DIR/app/$FLATPAK_ID"
export CHROME_DESKTOP="$FLATPAK_ID.desktop"
if [ -S "$XDG_RUNTIME_DIR/${WAYLAND_DISPLAY:-wayland-0}" ]; then
    set -- --ozone-platform=wayland "$@"
else
    unset WAYLAND_DISPLAY
    set -- --ozone-platform=x11 "$@"
fi
exec zypak-wrapper /app/extra/claude-desktop/claude-desktop "$@"
