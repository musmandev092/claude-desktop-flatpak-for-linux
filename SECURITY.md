# Security

Please report security problems privately through
[GitHub's private vulnerability reporting](https://github.com/musmandev092/claude-desktop-flatpak-for-linux/security/advisories/new),
not in public issues.

Problems in the Claude app itself go to Anthropic: https://www.anthropic.com/responsible-disclosure-policy

## How releases are protected

- Everything is built by GitHub Actions from this public repository; no release is made on anyone's computer.
- Pull requests are built and tested in a job with a read-only token and no secrets.
- Only the `publish` job on `main` can sign and deploy, and only after the build and tests passed.
- The Flatpak repository is signed with GPG key `633C2A74A8C7B2A4F67DAC05F6E3C4A7C815B241`
  (public key: [keys/flatpak-repo-public.asc](keys/flatpak-repo-public.asc)); Flatpak refuses unsigned or wrongly signed updates.
- Every release has a build provenance attestation; verify with
  `gh attestation verify BUILDINFO.json -R musmandev092/claude-desktop-flatpak-for-linux`.
- All actions and containers are pinned to exact commits/digests.
- The Claude app is downloaded from `downloads.claude.ai` on your computer and checked against the sha256 in the manifest.
