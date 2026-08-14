#!/usr/bin/env bash
# Bump the app to <version>, tag it v<version>, push. publish.yml then
# ships the PyPI dists (Test PyPI first, then PyPI) on the v* tag; the
# onefile/ARM64/deb/flatpak release (build.yml) rides the same tag.
# An optional nickname lands in the GitHub Release title:
#   ./scripts/release.sh [--dry-run] 1.1.0 "Supernova"
set -euo pipefail
cd "$(dirname "$0")/.."

DRY=0
if [ "${1:-}" = "--dry-run" ]; then DRY=1; shift; fi
VERSION="${1:?usage: ./scripts/release.sh [--dry-run] <version> [\"Nickname\"]}"
NICKNAME="${2:-}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "version must be X.Y.Z"; exit 1; }
TAG="v$VERSION"

if [ "$DRY" = 1 ]; then
  echo "dry-run: would set version $VERSION in pyproject.toml and src/podracer/__init__.py,"
  echo "move the CHANGELOG heading (nickname: ${NICKNAME:-none}), commit,"
  echo "tag $TAG, push main + $TAG (publish-app.yml + build.yml then run on the tag)"
  exit 0
fi

HEADING="## [$VERSION] - $(date +%Y-%m-%d)"
if [ -n "$NICKNAME" ]; then HEADING="$HEADING \"$NICKNAME\""; fi
# Move the [Unreleased] heading: write the release heading in its
# place, then insert a fresh [Unreleased] at the top (newest-first).
awk -v h="$HEADING" '
  BEGIN { printed = 0 }
  /^## \[Unreleased\]/ && !printed {
    print "## [Unreleased]";
    print "";
    print h;
    printed = 1;
    next
  }
  { print }
' CHANGELOG.md > CHANGELOG.md.tmp && mv CHANGELOG.md.tmp CHANGELOG.md

sed -i "s/^version = .*/version = \"$VERSION\"/" pyproject.toml
sed -i "s/^__version__ = .*/__version__ = \"$VERSION\"/" src/podracer/__init__.py

git add pyproject.toml src/podracer/__init__.py CHANGELOG.md
git commit -m "release $VERSION"
git tag "$TAG"
git push origin main "$TAG"
echo "pushed $TAG — publish-app.yml ships the app dists (publish the codec first)"
