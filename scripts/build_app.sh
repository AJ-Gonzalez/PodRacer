#!/usr/bin/env bash
# Build the macOS .app bundle from the committed PodRacer.spec, ad-hoc
# sign it, and (with --install) copy it to /Applications. The bundle is
# dist/PodRacer.app; the spec is the source of truth (hygiene rule:
# never rebuild with ad-hoc CLI flags).
set -euo pipefail
SECONDS=0
cd "$(dirname "$0")/.."

uv run pyinstaller PodRacer.spec --noconfirm --clean

# Ad-hoc signature: PyInstaller already ad-hoc signs the bundle, but
# re-sign explicitly so the step is visible and survives spec drift.
# A distribution build needs a real Developer ID + notarization (see
# PENDING); ad-hoc is correct for personal use only.
codesign --force --deep --sign - dist/PodRacer.app
codesign --verify --deep --strict dist/PodRacer.app \
    && echo "codesign verify: OK"

size=$(du -sh dist/PodRacer.app | cut -f1)
duration=$SECONDS
echo "Built dist/PodRacer.app ($size)"
echo "Took $((duration / 60)):$((duration % 60))"

if [[ "${1:-}" == "--install" ]]; then
    rm -rf /Applications/PodRacer.app
    cp -R dist/PodRacer.app /Applications/
    echo "Installed /Applications/PodRacer.app"
fi
