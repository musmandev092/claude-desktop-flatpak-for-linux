# claude-desktop: Anthropic's official Claude Desktop for Fedora, installed by dnf.
#
# This package contains NO Anthropic files. It pins one exact official .deb
# (source.conf: URL, size, SHA256) and lists every file in it (manifest,
# ghost.list). On install, %post runs claude-desktop-fetch, which downloads
# that .deb from downloads.claude.ai, verifies it and puts the files in place.
# The files are declared %ghost, so rpm owns them: `dnf remove` deletes them
# and `rpm -qf` names this package.
#
# Mirrors the .deb's maintainer scripts, minus the Ubuntu/Debian-only parts
# (AppArmor userns profile, apt repository registration).
#
# Built by tools/build-rpm.sh, which passes:
#   --define "claude_version X.Y.Z" --define "pkg_release N" [--define "with_ccd 1"]

%{!?claude_version: %{error: build with tools/build-rpm.sh}}
%{!?pkg_release: %global pkg_release 1}

%global debug_package %{nil}

Name:           claude-desktop
Version:        %{claude_version}
Release:        %{pkg_release}%{?dist}
Summary:        Claude Desktop (installs Anthropic's official Linux build)
# The packaging is MIT. Claude Desktop itself is Anthropic's proprietary
# software, downloaded from Anthropic at install time and never shipped here.
License:        MIT
URL:            https://github.com/musmandev092/claude-desktop-rpm
Source0:        claude-desktop-fetch
Source1:        claude-desktop-verify
Source2:        claude-desktop-fetch.service
Source3:        source.conf
Source4:        manifest
Source5:        ghost.list
Source6:        dirs.list
Source7:        LICENSE
ExclusiveArch:  x86_64
BuildRequires:  systemd-rpm-macros

# The .deb's Depends, as Fedora packages
Requires:       gtk3
Requires:       libnotify
Requires:       nss
Requires:       xdg-utils
Requires:       at-spi2-core
Requires:       libdrm
Requires:       mesa-libgbm
Requires:       libxcb
Requires:       libsecret
Requires:       glib2
Requires:       libXtst
Requires:       libuuid
Requires:       pipewire-libs
Requires:       xdg-desktop-portal
Requires:       (xdg-desktop-portal-gtk or xdg-desktop-portal-gnome or xdg-desktop-portal-kde)
# What claude-desktop-fetch needs
Requires:       bash
Requires:       coreutils
Requires:       curl
Requires:       bsdtar
Requires(post): bash coreutils curl bsdtar findutils systemd

# The .deb's Recommends worth having on a desktop
Recommends:     alsa-lib
Recommends:     libayatana-appindicator-gtk3
Recommends:     ca-certificates
Recommends:     gnome-keyring
# The .deb's remaining Recommends: Claude Code command sandbox, SSH remotes,
# Cowork's local VM. Only installed if you ask for them.
Suggests:       bubblewrap
Suggests:       socat
Suggests:       openssh-clients
Suggests:       qemu-system-x86
Suggests:       edk2-ovmf
Suggests:       virtiofsd

%description
Claude Desktop for Fedora, as a normal dnf package.

This package contains no Anthropic software. When it is installed or
updated, it downloads Anthropic's official Linux build of Claude Desktop
%{version} from downloads.claude.ai, checks it against the SHA256 pinned in
this signed package, verifies every file, and installs it unmodified.

Left out on purpose (Debian/Ubuntu only): the AppArmor user-namespace profile
and the apt repository. Chromium's setuid chrome-sandbox is kept as upstream
ships it. Check the installed files any time with claude-desktop-verify.

%prep
%setup -q -c -T

%build
# Nothing to build.

%install
install -D -m 0755 %{SOURCE0} %{buildroot}%{_bindir}/claude-desktop-fetch
install -D -m 0755 %{SOURCE1} %{buildroot}%{_bindir}/claude-desktop-verify
install -D -m 0644 %{SOURCE2} %{buildroot}%{_unitdir}/claude-desktop-fetch.service
install -D -m 0644 %{SOURCE3} %{buildroot}%{_datadir}/claude-desktop-rpm/source.conf
install -D -m 0644 %{SOURCE4} %{buildroot}%{_datadir}/claude-desktop-rpm/manifest
install -D -m 0644 %{SOURCE7} %{buildroot}%{_datadir}/licenses/%{name}/LICENSE
# Launcher links, the same targets as in the .deb (our links, not Anthropic files)
ln -s ../lib/claude-desktop/claude-desktop %{buildroot}%{_bindir}/claude-desktop
%if 0%{?with_ccd}
ln -s ../lib/claude-desktop/resources/bin/ccd %{buildroot}%{_bindir}/ccd
%endif
# Empty directories the app's files go into (owned so they are removed too)
while read -r d; do install -d -m 0755 "%{buildroot}$d"; done < %{SOURCE6}

%post
# Download and install the pinned official build. Never fail the transaction:
# on failure the files stay as they were and a boot-time retry is enabled.
%{_bindir}/claude-desktop-fetch --from-rpm || :

%preun
if [ "$1" -eq 0 ]; then
    systemctl disable claude-desktop-fetch.service >/dev/null 2>&1 || :
    rm -rf /var/lib/claude-desktop-rpm /var/cache/claude-desktop-rpm \
           %{_prefix}/lib/claude-desktop.rpmnew %{_prefix}/lib/claude-desktop.rpmold
    # rpm skips %%ghost files under the doc dir when docs are excluded
    # (tsflags=nodocs, e.g. container images), so remove them here.
    rm -rf %{_docdir}/claude-desktop
fi

%postun
if [ "$1" -eq 0 ]; then
    update-desktop-database -q %{_datadir}/applications >/dev/null 2>&1 || :
    update-mime-database %{_datadir}/mime >/dev/null 2>&1 || :
    gtk-update-icon-cache -q -t -f %{_datadir}/icons/hicolor >/dev/null 2>&1 || :
fi

%files -f %{SOURCE5}
%license %{_datadir}/licenses/%{name}/LICENSE
%{_bindir}/claude-desktop-fetch
%{_bindir}/claude-desktop-verify
%{_bindir}/claude-desktop
%if 0%{?with_ccd}
%{_bindir}/ccd
%endif
%{_unitdir}/claude-desktop-fetch.service
%{_datadir}/claude-desktop-rpm/

%changelog
* Wed Oct 21 2026 Muhammad Usman <mosman092@hotmail.com> - 3.1623.0-1
- First RPM release: installs Anthropic's official .deb payload at install time.
