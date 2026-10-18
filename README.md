# Claude Desktop for Linux — Flatpak (unofficial)

**No human involvement — install once, everything works.** One command installs it; no
setup, no config edits, no root. Every release is found, built, tested, signed and published
by GitHub Actions with no human step, and reaches you through `flatpak update`.

Anthropic's official Claude Desktop app as a signed Flatpak, built for **Fedora Atomic**
(Silverblue, Kinoite, Bazzite, Bluefin, Aurora) and any other distro with Flatpak.

> **On Ubuntu or Debian, use [Anthropic's official `.deb`](https://code.claude.com/docs/en/desktop-linux) instead.**
> On Fedora Workstation or Arch a native package works too; this Flatpak is the same everywhere and needs no root.

## Install

```sh
flatpak install --user https://musmandev092.github.io/claude-desktop-flatpak-for-linux/claude-desktop.flatpakref
```

That's it. Updates arrive through `flatpak update`, GNOME Software or KDE Discover.

## What works

- Chat, projects, sign-in
- **Claude Code** with your real tools (`git`, shell, SSH keys)
- **MCP plugins** (`npx`, `uvx`, `docker` …) with no config changes
- **Cowork** — runs in Anthropic's cloud and reaches the folders you connect

## Atomic desktops

Everything runs on your real system, exactly like a normal terminal. On Silverblue, Bazzite
and friends just tell Claude *"this is an atomic desktop, use a toolbox"* — it runs
`toolbox create`, `toolbox run …` itself. For MCP plugins, install their tools on the host as
usual (e.g. `rpm-ostree install nodejs uv`), exactly like the native app.

## How it works

- Flatpak downloads the official `.deb` from `downloads.claude.ai` at install time and checks
  its SHA-256. Nothing from Anthropic is redistributed and Claude runs unmodified.
- A small bridge links every host command into the sandbox, so Claude Code and plugins use
  your tools. Plugins stop when Claude quits.
- The bridge ships as a separate small extension (`io.github.musmandev092.ClaudeDesktop.Bridge`),
  installed and updated together with the app. Fixes to it are tiny updates; you only download
  Claude again when Anthropic releases a new version.
- **No human in the loop:** GitHub Actions checks Anthropic's repository every hour,
  builds, install-tests, scans, signs and publishes each new version. If anything fails,
  nothing is published.

Verify a build: `gh attestation verify BUILDINFO.json -R musmandev092/claude-desktop-flatpak-for-linux`
(download `BUILDINFO.json` from the site). Signing key fingerprint:
`633C 2A74 A8C7 B2A4 F67D AC05 F6E3 C4A7 C815 B241`.

## Security

Claude Code and plugins can run commands on your host, like the Claude Code CLI does.
The Flatpak sandbox does not limit what Claude runs. Report issues privately: see [SECURITY.md](SECURITY.md).

## Disclaimer

Unofficial community project, not affiliated with Anthropic. "Claude" is a trademark of
Anthropic, PBC. Packaging is [MIT](LICENSE); bundled host-spawn is MIT-0.
