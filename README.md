# Claude Desktop for Linux — Flatpak (unofficial)

Run the official **Claude Desktop** app on **any Linux distribution** — Fedora,
Fedora Silverblue / Kinoite / Bazzite, Arch, openSUSE, Linux Mint and more —
packaged as a **Flatpak** with **automatic updates**.

Anthropic ships Claude Desktop for Linux only as a `.deb` for Ubuntu and Debian.
This Flatpak runs the same official app everywhere else, with everything working:

- ✅ Chat, projects and sign-in with your claude.ai account
- ✅ **Claude Code** sessions and the built-in terminal, using your real tools
- ✅ **All local MCP plugins** (`npx`, `uvx`, `docker`, …) — no config changes needed
- ✅ **Cowork** with its virtual machine (needs KVM)
- ✅ Atomic/immutable desktops: plugins can run inside your **toolbox**
- ✅ Automatic updates, hours after Anthropic releases a new version

📖 **Website and step-by-step guides:** [Fedora](https://musmandev092.github.io/claude-desktop-flatpak-for-linux/fedora/) ·
[Silverblue / Kinoite / Bazzite / Bluefin](https://musmandev092.github.io/claude-desktop-flatpak-for-linux/fedora-silverblue/) ·
[Arch / Manjaro / CachyOS](https://musmandev092.github.io/claude-desktop-flatpak-for-linux/arch-linux/) ·
[Cowork on Linux](https://musmandev092.github.io/claude-desktop-flatpak-for-linux/cowork-linux/) ·
[MCP servers & Claude Code](https://musmandev092.github.io/claude-desktop-flatpak-for-linux/mcp-plugins/)

## Install Claude Desktop on Fedora, Silverblue, Arch or any Linux

```sh
flatpak install --user https://musmandev092.github.io/claude-desktop-flatpak-for-linux/claude-desktop.flatpakref
```

Open **Claude** from your app menu, or run:

```sh
flatpak run io.github.musmandev092.ClaudeDesktop
```

Updates come with `flatpak update` or GNOME Software / KDE Discover.

## Settings

Optional file: `~/.config/claude-desktop-flatpak/settings.conf`

```sh
# Run plugins and Claude Code inside a toolbox (Silverblue, Kinoite, Bazzite…).
# Leave empty to run them directly on the host.
TOOLBOX=dev

# Run Claude without the Cowork patch (Cowork turns off, everything else works).
#COWORK=off

# Run the Cowork VM on THIS computer (opt-in, see "Cowork" below).
#COWORK_LOCAL=on
```

Restart the app after changing it.

### MCP plugins

Your MCP config lives at
`~/.var/app/io.github.musmandev092.ClaudeDesktop/config/Claude/claude_desktop_config.json`
and works exactly like the official docs describe — `"command": "npx"` just works.

For a command given as an **absolute path**, or to use a **different toolbox** for one
plugin, use `host-run`:

```json
"command": "host-run",
"args": ["--toolbox", "other-box", "/home/me/.local/bin/my-mcp-server"]
```

New tools you install are picked up **after restarting** the app.

### Cowork

By default, Cowork runs in **Anthropic's cloud VM**. It works, and your
files still reach your folders.

To run the Cowork VM **on your own computer** instead, add `COWORK_LOCAL=on` to
`settings.conf` and restart the app.

⚠️ **What this does:** Cowork's helper talks to its VM over a *vsock* socket,
and Flatpak blocks vsock for every app. With `COWORK_LOCAL=on`, the helper and
QEMU run **outside the Flatpak sandbox**, in a small bubblewrap container on
your host (using the QEMU, firmware and virtiofsd bundled in this Flatpak).
That removes a sandbox protection for the VM, so it is off by default.

Needs hardware virtualisation (KVM) and the `vhost_vsock` kernel module. If the
Cowork tab says it lacks permission, add yourself to the `kvm` group:

```sh
sudo usermod -aG kvm $USER   # then log out and back in
```

## How it works — and why it's legal

- This repository contains **only packaging files** (MIT licence). It does **not**
  contain or redistribute the Claude app. The only Anthropic file in the published
  Flatpak is Claude's icon, taken from the official `.deb` at build time so the app
  looks right in your menu.
- When you install, Flatpak downloads the **official** `.deb` directly from
  `downloads.claude.ai` and verifies its SHA-256 checksum (Flatpak *extra-data*).
- **Plugin bridge:** every command on your host (or toolbox) is linked into the
  sandbox automatically. Calls go out through the Flatpak portal
  (`flatpak-spawn --host`, or [host-spawn](https://github.com/1player/host-spawn)
  for terminals), and plugins stop when Claude exits.
- **Cowork:** Claude looks for its VM firmware and `virtiofsd` under `/usr`, which a
  Flatpak cannot provide. At install time a copy of `app.asar` gets two same-length
  path strings changed (`/usr/...` → `/app/...`). The original is kept; if the patch
  doesn't apply or the app fails to start, it falls back to the original automatically.
- **Updates:** every hour GitHub Actions checks Anthropic's apt repository; a new
  version is built, install-tested (including a Cowork canary) and security-scanned,
  and only then committed, GPG-signed and published to GitHub Pages – see below.

## Security note

To make plugins and Claude Code work, this Flatpak can run commands on your host
(`--talk-name=org.freedesktop.Flatpak`) and read your home folder. That is the same
trust level as running the Claude Code CLI directly — the Flatpak sandbox does **not**
protect you from what Claude runs.

## Build it yourself

```sh
flatpak install --user flathub org.flatpak.Builder
flatpak run org.flatpak.Builder --user --install-deps-from=flathub --force-clean \
    --repo=repo build-dir io.github.musmandev092.ClaudeDesktop.yaml
flatpak remote-add --user --no-gpg-verify claude-local repo
flatpak install --user claude-local io.github.musmandev092.ClaudeDesktop
```

## How releases are made – no human step

Everything runs in public on GitHub Actions ([`.github/workflows/build.yml`](.github/workflows/build.yml)):

| Job | Runs | Can it publish? |
|---|---|---|
| **Check** | every hour: new Claude / OVMF version? | no – read-only |
| **Build and test** | builds from this repo, installs like a user, Cowork canary | no – read-only, no secrets |
| **Security checks** | gitleaks (whole history), zizmor, actionlint, ShellCheck | no – read-only |
| **Sign and publish** | only on `main`, only if all of the above passed: commit the update as `github-actions[bot]`, GPG-sign, deploy, attest, release | yes |

Nobody builds a release on their own computer. If a new Claude version breaks
anything, nothing is published and the failed run stays public. Actions and
containers are pinned to exact commits/digests; Dependabot updates them and its
pull requests are merged only when every check passed on the exact commit.

**Verify a release yourself:**

```sh
curl -sO https://musmandev092.github.io/claude-desktop-flatpak-for-linux/BUILDINFO.json
gh attestation verify BUILDINFO.json -R musmandev092/claude-desktop-flatpak-for-linux
flatpak info io.github.musmandev092.ClaudeDesktop | grep Commit   # = flatpak_commit in BUILDINFO.json
```

Signing key: `633C 2A74 A8C7 B2A4 F67D  AC05 F6E3 C4A7 C815 B241`
([public key](keys/flatpak-repo-public.asc)). See also [SECURITY.md](SECURITY.md).

## Tests

Run against the installed app (close Claude first):

```sh
tests/run-tests.sh        # 31 checks: install, bridge, MCP plugins, Cowork VM boot, GUI
tests/extreme-tests.sh    # 46 edge cases: odd arguments, 100 MB pipes, signals, 50 parallel
                          # calls, missing/stopped toolbox, X11, no KVM, crashes, leaked secrets
```

Fuzz testing (Claude may stay open): 10,000 generated scenarios, each checked
against what should happen, with latency/throughput numbers and leak checks.

```sh
tests/fuzz-tests.sh                 # 10,000 scenarios (a different set: --seed N)
tests/fuzz-tests.sh --only 1234     # replay one scenario exactly
tests/fuzz-tests.sh --fallback      # force the slower `toolbox run` path
```

Security tests (Claude may stay open): shellshock-style environment variables and
injected arguments never run, API keys in job files stay private (0600 in a 0700
folder) and are never left behind, toolbox names cannot pick another container,
a user's `~/.bashrc` cannot leak into a plugin's output, and the published
repository rejects a wrong signing key.

```sh
tests/security-tests.sh             # 20 checks
tests/lint-scripts.sh               # every script (and every script embedded in host-run) parses
```

| Area | Scenarios | What is generated |
|---|---|---|
| roundtrip | 3,500 | odd/binary/100 KB arguments, 1 MB of env vars, up to 16 MB stdin/4 MB stdout, odd folders, exit codes |
| exitcode | 1,000 | every exit code 0–255, missing (127) and non-executable (126) commands |
| signal | 400 | Ctrl-C / SIGTERM / SIGHUP early and late; nothing may be left running |
| burst | 100 | 5–80 commands started at the same moment |
| mcp | 400 | 1–200 JSON messages per plugin session, lock-step and pipelined |
| cache | 300 | corrupted, missing, FIFO, directory or unreadable toolbox cache |
| config | 1,300 | broken settings.conf: garbage, binary, CRLF, quotes, `export`, bad names |
| patcher | 3,000 | valid, truncated, corrupted and hostile app.asar files for the Cowork patch |

Known limits (from Flatpak/toolbox, reproduced without this project):
`flatpak-spawn` can lose a signal sent in the first ~50 ms while the command is
still starting (about 1 in 200 under heavy load); on the fallback path Ctrl-C
reaches the command as SIGTERM.

## Disclaimer

This is an **unofficial** community project. It is **not affiliated with, endorsed
by, or supported by Anthropic**. "Claude" is a trademark of Anthropic, PBC.
Claude Desktop itself is subject to Anthropic's terms.
If Anthropic publishes an official Flatpak or Fedora package, please use that instead.

Packaging built with the help of an AI assistant (Claude).

## License

Packaging files: [MIT](LICENSE). Bundled: QEMU (GPL-2.0), libslirp (BSD-3-Clause),
libcap-ng (LGPL-2.1), OVMF/EDK II (BSD-2-Clause-Patent), host-spawn (MIT-0).
