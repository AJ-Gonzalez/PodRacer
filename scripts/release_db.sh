#!/usr/bin/env bash
# Bump the codec to <version>, tag it db-v<version>, push. publish.yml
# then ships the podracer_db dists (Test PyPI first, then PyPI) on the
# db-v* tag. The codec versions independently of the app.
#   ./scripts/release_db.sh [--dry-run] 1.1.0
set -euo pipefail
cd "$(dirname "$0")/.."

DRY=0
if [ "${1:-}" = "--dry-run" ]; then DRY=1; shift; fi
VERSION="${1:?usage: ./scripts/release_db.sh [--dry-run] <version>}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "version must be X.Y.Z"; exit 1; }
TAG="db-v$VERSION"

if [ "$DRY" = 1 ]; then
  echo "dry-run: would set version $VERSION in packages/podracer_db/pyproject.toml and"
  echo "packages/podracer_db/src/podracer_db/__init__.py, commit, tag $TAG, push main + $TAG"
  exit 0
fi

sed -i "s/^version = .*/version = \"$VERSION\"/" packages/podracer_db/pyproject.toml
sed -i "s/^__version__ = .*/__version__ = \"$VERSION\"/" packages/podracer_db/src/podracer_db/__init__.py

git add packages/podracer_db/pyproject.toml packages/podracer_db/src/podracer_db/__init__.py
git commit -m "release podracer_db $VERSION"
git tag "$TAG"
git push origin main "$TAG"
echo "pushed $TAG — publish-db.yml ships the codec dists"
