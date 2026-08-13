#!/usr/bin/env bash
# Build the one-file executable at the repo root (symlink into $PATH):
#   ln -s "$PWD/podracer" ~/.local/bin/podracer
# The binary is gitignored; rebuild after app changes. The output name
# defaults to podracer; pass podracer-arm64 for an ARM64 build.
set -euo pipefail
SECONDS=0
cd "$(dirname "$0")/.."
NAME="${1:-podracer}"

pyinstaller --onefile --name "$NAME" --clean --noconfirm \
    --paths src --paths packages/podracer_db/src \
    --add-data "src/podracer/fonts:podracer/fonts" --add-data "src/podracer/assets:podracer/assets" src/podracer/main.py

cp "dist/$NAME" "./$NAME"
chmod +x "./$NAME"
size=$(du -h "./$NAME" | cut -f1)
duration=$SECONDS
echo "Built ./$NAME ($size)"
echo "Took $((duration / 60)):$((duration % 60))"
