# Security

Report problems privately via
[GitHub private vulnerability reporting](https://github.com/musmandev092/claude-desktop-flatpak-for-linux/security/advisories/new),
not in public issues. Bugs in the Claude app itself go to
[Anthropic](https://www.anthropic.com/responsible-disclosure-policy).

## How releases are protected

- Built by GitHub Actions from this public repository; nothing is released from a personal computer.
- Pull requests build in a read-only job without secrets; only `publish` on `main` signs and deploys, after tests pass.
- The Flatpak repository is GPG-signed (key `633C2A74A8C7B2A4F67DAC05F6E3C4A7C815B241`, [public key](keys/flatpak-repo-public.asc)); Flatpak refuses unsigned or wrongly signed updates.
- Releases carry a build provenance attestation:
  `gh attestation verify BUILDINFO.json -R musmandev092/claude-desktop-flatpak-for-linux`
- Actions and containers are pinned to exact commits/digests.
- Claude is downloaded from `downloads.claude.ai` on your computer and checked against the sha256 in the manifest.
