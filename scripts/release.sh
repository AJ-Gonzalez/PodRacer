#!/usr/bin/env bash
# Bump the app to <version>, tag it v<version>, push. publish.yml then
# ships the PyPI dists (Test PyPI first, then PyPI) on the v* tag; the
# onefile binary release (build.yml) rides the same tag.
#   ./scripts/release.sh [--dry-run] 1.1.0
set -euo pipefail
cd "$(dirname "$0")/.."

DRY=0
if [ "${1:-}" = "--dry-run" ]; then DRY=1; shift; fi
VERSION="${1:?usage: ./scripts/release.sh [--dry-run] <version>}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "version must be X.Y.Z"; exit 1; }
TAG="v$VERSION"

if [ "$DRY" = 1 ]; then
  echo "dry-run: would set version $VERSION in pyproject.toml and src/podracer/__init__.py,"
  echo "commit, tag $TAG, push main + $TAG (publish.yml + build.yml then run on the tag)"
  exit 0
fi

sed -i "s/^version = .*/version = \"$VERSION\"/" pyproject.toml
sed -i "s/^__version__ = .*/__version__ = \"$VERSION\"/" src/podracer/__init__.py

git add pyproject.toml src/podracer/__init__.py
git commit -m "release $VERSION"
git tag "$TAG"
git push origin main "$TAG"
echo "pushed $TAG — publish.yml ships the app dists"
