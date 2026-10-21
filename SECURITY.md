# Security

Report problems privately via
[GitHub private vulnerability reporting](https://github.com/musmandev092/claude-desktop-rpm/security/advisories/new),
not in public issues. Bugs in the Claude app itself go to
[Anthropic](https://www.anthropic.com/responsible-disclosure-policy).

## How releases are protected

- Built by GitHub Actions from this public repository; nothing is released from a personal computer.
- Pull requests build and test in read-only jobs without secrets; only `publish` on `main` signs and deploys, after the build, install test and security checks pass.
- The RPM and the repository metadata are GPG-signed (key `9A67611264AD59383EFA3AA1E0B0E56DCFAE37BB`, [public key](keys/RPM-GPG-KEY-claude-desktop-rpm.asc)); the `.repo` file sets `gpgcheck=1` and `repo_gpgcheck=1`, so dnf refuses unsigned or wrongly signed packages and metadata.
- Releases carry a build provenance attestation:
  `gh attestation verify BUILDINFO.json -R musmandev092/claude-desktop-rpm`
- Actions and containers are pinned to exact commits/digests.
- The newest Claude build is read from Anthropic's GPG-signed apt index (key `31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE`, [public key](keys/anthropic-release-key.asc)), and its SHA-256 is pinned in the signed RPM. On your computer, the `.deb` is downloaded from `downloads.claude.ai`, checked against that SHA-256, and every unpacked file is checked against the package's file list before anything is installed.
