#!/bin/bash
#
# build-rpm.sh - build the small claude-desktop RPM for the newest official
# Claude Desktop Linux build. The RPM contains no Anthropic files: only our
# scripts, the pinned source (URL, size, SHA256) and the file manifest.
#
# Chain of trust (nothing is used until each step checks out):
#   pinned key (keys/anthropic-release-key.asc) -> InRelease signature + Valid-Until
#   -> Packages SHA256 -> newest claude-desktop entry -> .deb SHA256
# The verification approach follows dewzor/claude-desktop-fedora (MIT/Apache-2.0).
#
# Usage: tools/build-rpm.sh [--outdir DIR] [--release N] [--print-latest]
#   --print-latest  verify the signed index, print "VERSION SHA256 SIZE", exit
# Needs: curl gpg sha256sum bsdtar rpmbuild (sudo dnf install bsdtar rpm-build)
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
APT_BASE="https://downloads.claude.ai/claude-desktop/apt/stable"
KEY_FILE="$HERE/keys/anthropic-release-key.asc"
KEY_FPR="31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"  # Anthropic public key fingerprint, gitleaks:allow
ARCH_DEB="amd64"
APP=/usr/lib/claude-desktop
OUTDIR="$HERE/out"
RELEASE=1
PRINT_LATEST=0

die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
info() { printf '==> %s\n' "$*"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --outdir)       OUTDIR="${2:?}"; shift 2 ;;
        --release)      RELEASE="${2:?}"; shift 2 ;;
        --print-latest) PRINT_LATEST=1; shift ;;
        -h|--help)      sed -n '3,15p' "$0"; exit 0 ;;
        *)              die "unknown option: $1" ;;
    esac
done
[[ "$RELEASE" =~ ^[1-9][0-9]{0,5}$ ]] || die "--release must be a positive number"

for c in curl gpg sha256sum awk; do command -v "$c" >/dev/null || die "missing command: $c"; done
[ "$PRINT_LATEST" -eq 1 ] || for c in bsdtar rpmbuild rpm; do
    command -v "$c" >/dev/null || die "missing command: $c (sudo dnf install bsdtar rpm-build)"
done

WORK="$(mktemp -d -t claude-rpm.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
sha256_of() { sha256sum -- "$1" | cut -d' ' -f1; }

# ---- 1. verify Anthropic's signed index -------------------------------------
GNUPGHOME="$WORK/gnupg"; export GNUPGHOME
mkdir -m 700 "$GNUPGHOME"
gpg --batch --quiet --import "$KEY_FILE" 2>/dev/null || die "cannot import $KEY_FILE"
gpg --batch --with-colons --fingerprint 2>/dev/null | grep -q "^fpr:::::::::$KEY_FPR:" \
    || die "key file fingerprint is not $KEY_FPR"

curl -fsS --max-time 60 -o "$WORK/InRelease" "$APT_BASE/dists/stable/InRelease" || die "cannot fetch InRelease"
# --decrypt writes only the signed text, so nothing below reads unsigned bytes.
status="$(gpg --batch --status-fd 1 --output "$WORK/Release" --decrypt "$WORK/InRelease" 2>/dev/null)" \
    || die "InRelease signature check failed"
# gpg exits 0 even for expired/revoked keys: require GOODSIG + VALIDSIG by the pinned key.
printf '%s\n' "$status" | awk -v f="$KEY_FPR" '
    $2 ~ /^(BADSIG|ERRSIG|EXPSIG|EXPKEYSIG|REVKEYSIG)$/ { bad = 1 }
    $2 == "GOODSIG" { good = 1 }
    $2 == "VALIDSIG" && $NF == f { pinned = 1 }
    END { exit !(good && pinned && !bad) }' || die "InRelease is not validly signed by $KEY_FPR"

valid_until="$(sed -n 's/^Valid-Until: //p' "$WORK/Release")"
[ -n "$valid_until" ] || die "signed index has no Valid-Until"
[ "$(date -d "$valid_until" +%s)" -gt "$(date +%s)" ] || die "signed index expired ($valid_until)"

index="main/binary-$ARCH_DEB/Packages"
want="$(awk -v p="$index" '/^SHA256:/{s=1;next} /^[^ ]/{s=0} s && $3==p {print $1}' "$WORK/Release")"
[ -n "$want" ] || die "signed index does not list $index"
curl -fsS --max-time 120 -o "$WORK/Packages" "$APT_BASE/dists/stable/$index" || die "cannot fetch $index"
[ "$(sha256_of "$WORK/Packages")" = "$want" ] || die "$index does not match the signed index"

entry="$(awk -v RS= -v arch="$ARCH_DEB" '
    {
        delete v; n = split($0, l, "\n")
        for (i = 1; i <= n; i++) if (l[i] ~ /^[A-Za-z0-9-]+: /) { k = l[i]; sub(/: .*/, "", k); v[k] = substr(l[i], length(k) + 3) }
        if (v["Package"] == "claude-desktop" && v["Architecture"] == arch)
            print v["Version"] "\t" v["SHA256"] "\t" v["Filename"] "\t" v["Size"]
    }' "$WORK/Packages" | sort -t $'\t' -k1,1V | tail -1)"
IFS=$'\t' read -r VERSION SHA FILENAME SIZE <<<"$entry"
[[ "$VERSION"  =~ ^[0-9][0-9A-Za-z.+~]*$ ]] || die "unexpected Version: $VERSION"
[[ "$SHA"      =~ ^[0-9a-f]{64}$ ]]         || die "unexpected SHA256: $SHA"
[[ "$SIZE"     =~ ^[0-9]{1,12}$ ]]          || die "unexpected Size: $SIZE"
[[ "$FILENAME" =~ ^pool/[A-Za-z0-9._+~/-]+\.deb$ && "$FILENAME" != *..* ]] || die "unexpected Filename: $FILENAME"
[[ "$VERSION" != *-* ]] || die "Version $VERSION has a '-', which rpm does not allow"

if [ "$PRINT_LATEST" -eq 1 ]; then
    printf '%s %s %s\n' "$VERSION" "$SHA" "$SIZE"; exit 0
fi
info "claude-desktop $VERSION (Anthropic's signed index verified)"

# ---- 2. download and verify the .deb (it never leaves this machine) ---------
info "downloading $FILENAME ($(( SIZE / 1048576 )) MB) ..."
curl -fsSL --globoff --max-time 900 -o "$WORK/claude.deb" "$APT_BASE/$FILENAME" || die "download failed"
[ "$(sha256_of "$WORK/claude.deb")" = "$SHA" ] || die ".deb does not match the signed SHA256"
info ".deb matches the signed SHA256"

# ---- 3. unpack exactly as claude-desktop-fetch will on the user's machine ----
R="$WORK/root"
mkdir "$WORK/deb" "$R"
bsdtar -xf "$WORK/claude.deb" -C "$WORK/deb" 'data.tar.*'
rm -f "$WORK/claude.deb"
bsdtar -xpf "$(find "$WORK/deb" -maxdepth 1 -name 'data.tar.*' -print -quit)" -C "$R"
rm -rf "$WORK/deb"
[ -d "$R$APP" ] || die "unexpected payload layout"
[ -f "$R$APP/chrome-sandbox" ] || die "payload has no chrome-sandbox"
res="$R$APP/resources"
cp_into() { if [ -f "$1" ]; then install -D -m 0644 "$1" "$R$2"; fi; }
cp_into "$res/linux-mime/com.anthropic.Claude.xml" /usr/share/mime/packages/com.anthropic.Claude.xml
cp_into "$res/gnome-search-provider/com.anthropic.Claude.search-provider.ini" \
        /usr/share/gnome-shell/search-providers/com.anthropic.Claude.search-provider.ini
cp_into "$res/gnome-search-provider/com.anthropic.Claude.SearchProvider.service" \
        /usr/share/dbus-1/services/com.anthropic.Claude.SearchProvider.service
rm -rf "${R:?}/usr/share/lintian" "${R:?}/usr/bin"
chmod 4755 "$R$APP/chrome-sandbox"

# Paths go into rpm %files and a space-separated manifest: refuse anything odd.
if (cd "$R" && find usr | grep -n '[^A-Za-z0-9._+@,=~/-]' | head -5 | grep .); then
    die "payload has file names with unusual characters (listed above); the generator must be extended"
fi

# ---- 4. write the per-version lists -----------------------------------------
S="$WORK/sources"
mkdir "$S"
( cd "$R"
  find usr -type d -printf 'D %m /%p\n'
  find usr -type l -printf 'L %l /%p\n'
  find usr -type f -printf '%m /%p\n' | while read -r m p; do
      printf 'F %s %s %s\n' "$m" "$(sha256sum "./$p" | cut -d' ' -f1)" "$p"
  done
) | sort -k1,1 -k3 > "$S/manifest"

# Directories this package owns: the app tree, its doc dir, the search-provider dirs.
{
    (cd "$R" && find "${APP#/}" -type d -printf '/%p\n')
    [ -d "$R/usr/share/doc/claude-desktop" ] && (cd "$R" && find usr/share/doc/claude-desktop -type d -printf '/%p\n')
    [ -d "$R/usr/share/gnome-shell/search-providers" ] && printf '%s\n' /usr/share/gnome-shell /usr/share/gnome-shell/search-providers
} | sort -u > "$S/dirs.list"

{
    sed 's|^|%dir |' "$S/dirs.list"
    awk '$1 == "F" { printf "%%ghost %%attr(%s,root,root) %s\n", $2, $4 }
         $1 == "L" { printf "%%ghost %s\n", $3 }' "$S/manifest"
} > "$S/ghost.list"

cat > "$S/source.conf" <<EOF
VERSION=$VERSION
DEB_URL=$APT_BASE/$FILENAME
DEB_SHA256=$SHA
DEB_SIZE=$SIZE
EOF

cp "$HERE/scripts/claude-desktop-fetch" "$HERE/scripts/claude-desktop-verify" \
   "$HERE/scripts/claude-desktop-fetch.service" "$HERE/LICENSE" "$S/"

# The fetch script will verify the user's unpacked tree against this manifest;
# check now that the manifest matches the tree it was made from.
"$HERE/scripts/claude-desktop-verify" --root "$R" --manifest "$S/manifest" >/dev/null \
    || die "manifest self-check failed"

ccd=()
[ -x "$R$APP/resources/bin/ccd" ] && ccd=(--define "with_ccd 1")
counts="$(awk '{c[$1]++} END {printf "%d files, %d links, %d dirs", c["F"], c["L"], c["D"]}' "$S/manifest")"
rm -rf "$R"

# ---- 5. build -----------------------------------------------------------------
RB="$WORK/rpmbuild"
info "building RPM ($counts listed as %ghost) ..."
rpmbuild --define "_topdir $RB" --define "_sourcedir $S" \
    --define "claude_version $VERSION" --define "pkg_release $RELEASE" "${ccd[@]}" \
    -ba "$HERE/claude-desktop.spec" > "$WORK/rpmbuild.log" 2>&1 \
    || { tail -30 "$WORK/rpmbuild.log" >&2; die "rpmbuild failed"; }

rpm_file="$(find "$RB/RPMS" -name '*.rpm' -print -quit)"
srpm_file="$(find "$RB/SRPMS" -name '*.rpm' -print -quit)"
[ -n "$rpm_file" ] && [ -n "$srpm_file" ] || die "rpmbuild produced no RPM"

# ---- 6. no Anthropic files inside: every real (non-ghost) file must be ours ---
allowed='^/usr/bin/(claude-desktop-fetch|claude-desktop-verify|claude-desktop|ccd)$|^/usr/lib/systemd/system/claude-desktop-fetch\.service$|^/usr/share/claude-desktop-rpm(/(source\.conf|manifest))?$|^/usr/share/licenses/claude-desktop(/LICENSE)?$'
dirs_re="$(sed 's/[.[\*^$+?(){}|]/\\&/g; s/.*/^&$/' "$S/dirs.list" | paste -sd'|')"
if rpm -qlp --noghost "$rpm_file" | grep -Ev "$allowed" | grep -Ev "$dirs_re" | grep .; then
    die "the RPM contains files that are not ours (listed above); refusing to publish"
fi
if rpm2cpio "$rpm_file" | bsdtar -tf - | grep -E '\.(deb|asar|node|so|pak|bin|png)$'; then
    die "the RPM payload contains Anthropic-looking files"
fi

mkdir -p "$OUTDIR"
cp -- "$rpm_file" "$srpm_file" "$OUTDIR/"
cp -- "$S/source.conf" "$OUTDIR/"
info "built $(basename "$rpm_file") ($(du -h "$rpm_file" | cut -f1)) and $(basename "$srpm_file")"
info "no Anthropic files inside; it pins $FILENAME ($SHA)"
