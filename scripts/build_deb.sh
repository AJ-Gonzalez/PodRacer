#!/usr/bin/env bash
# Build a .deb from the onefile binary (Debian/Ubuntu/Mint family).
# Run after scripts/build_onefile.sh: the binary name and architecture
# come from the build machine (amd64 -> podracer, arm64 -> podracer-arm64).
# Output: dist/podracer_<version>_<arch>.deb
set -euo pipefail
SECONDS=0
cd "$(dirname "$0")/.."

ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
if [ "$ARCH" = "arm64" ]; then BIN="podracer-arm64"; else BIN="podracer"; fi
[ -x "./$BIN" ] || { echo "build the onefile first: bash scripts/build_onefile.sh $BIN" >&2; exit 1; }

VERSION="$(python3 -c \
  "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
PKG="podracer_${VERSION}_${ARCH}"

ROOT="$(mktemp -d)"
mkdir -p "$ROOT/usr/bin" \
         "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/metainfo" \
         "$ROOT/usr/share/icons/hicolor/256x256/apps" \
         "$ROOT/DEBIAN"
cp "./$BIN" "$ROOT/usr/bin/podracer"
chmod 755 "$ROOT/usr/bin/podracer"
cp packaging/io.github.ajgonzalez.PodRacer.desktop \
   "$ROOT/usr/share/applications/io.github.ajgonzalez.PodRacer.desktop"
cp packaging/io.github.ajgonzalez.PodRacer.appdata.xml \
   "$ROOT/usr/share/metainfo/io.github.ajgonzalez.PodRacer.appdata.xml"
cp src/podracer/assets/podracer_icon.png \
   "$ROOT/usr/share/icons/hicolor/256x256/apps/io.github.ajgonzalez.PodRacer.png"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: podracer
Version: $VERSION
Section: sound
Priority: optional
Architecture: $ARCH
Depends: ffmpeg, udisks2, libgl1, libegl1, libxkbcommon0, libfontconfig1, libdbus-1-3
Maintainer: PodRacer Maintainers <podracer@users.noreply.github.com>
Description: Transfer music to an iPod from Linux, no iTunes
 Midnight-commander-style two-pane UI: browse your music folder on the
 left, see what is on the iPod on the right. Manual sync, automatic
 duplicate avoidance, auto-transcode via ffmpeg.
EOF

mkdir -p dist
dpkg-deb --build --root-owner-group "$ROOT" "dist/$PKG.deb" >/dev/null
rm -rf "$ROOT"
size=$(du -h "dist/$PKG.deb" | cut -f1)
duration=$SECONDS
echo "Built dist/$PKG.deb ($size)"
echo "Took $((duration / 60)):$((duration % 60))"
