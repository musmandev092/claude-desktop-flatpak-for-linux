# Claude Desktop for Fedora — RPM (unofficial)

Anthropic's official Claude Desktop for Linux, as a normal **dnf** package for Fedora.
Install once; updates arrive with `sudo dnf upgrade`.

> **On Ubuntu or Debian, use [Anthropic's official `.deb`](https://code.claude.com/docs/en/desktop-linux) instead.**

## Install

```sh
sudo dnf config-manager addrepo --from-repofile=https://musmandev092.github.io/claude-desktop-rpm/claude-desktop.repo
sudo dnf install claude-desktop
```

dnf asks you to trust the repository key once. Its fingerprint is
`9A67 6112 64AD 5938 3EFA 3AA1 E0B0 E56D CFAE 37BB`.

## How it works

- **No Anthropic software is hosted here.** The `claude-desktop` package is a few hundred KB:
  our install scripts, plus the exact URL, size and SHA-256 of one official `.deb` and a list
  of every file in it.
- When dnf installs or updates the package, it downloads that `.deb` from
  `downloads.claude.ai`, checks the SHA-256, verifies every file, and puts Claude in place
  **unmodified** — the same files Ubuntu users get.
- rpm owns all of Claude's files (`%ghost`), so `sudo dnf remove claude-desktop` removes
  everything, and `rpm -qf` names the package.
- Same as the `.deb`, minus two Debian/Ubuntu-only steps: the AppArmor profile (Fedora does
  not need it) and the apt repository (this dnf repository replaces it).
- **No human in the loop:** GitHub Actions checks Anthropic's signed apt index every hour,
  builds the package, install-tests it in a clean Fedora container (real download, tamper
  check, offline retry, clean removal), scans, signs and publishes. If anything fails,
  nothing is published.

## Commands

| Command | What it does |
|---|---|
| `claude-desktop-verify` | Checks every installed file against the package's SHA-256 list |
| `sudo claude-desktop-fetch` | Downloads and installs the pinned build again (repairs a broken install) |

If the download fails during install (offline), dnf still finishes and a one-time service
retries at the next boot.

## Verify a build

`gh attestation verify BUILDINFO.json -R musmandev092/claude-desktop-rpm`
(download `BUILDINFO.json` from the site or a release).

## Security

Report issues privately: see [SECURITY.md](SECURITY.md).

## Disclaimer

Unofficial community project, not affiliated with Anthropic. "Claude" is a trademark of
Anthropic, PBC. Packaging is [MIT](LICENSE). Claude Desktop itself is Anthropic's software,
downloaded from Anthropic under their terms.
