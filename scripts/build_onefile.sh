#!/usr/bin/env bash
# Build the one-file executable at the repo root (symlink into $PATH):
#   ln -s "$PWD/podracer" ~/.local/bin/podracer
# The binary is gitignored; rebuild after app changes.
set -euo pipefail
SECONDS=0
cd "$(dirname "$0")/.."

pyinstaller --onefile --name podracer --clean --noconfirm \
    --paths src --add-data "src/podracer/fonts:podracer/fonts" --add-data "src/podracer/assets:podracer/assets" src/podracer/main.py

cp dist/podracer ./podracer
chmod +x ./podracer
size=$(du -h ./podracer | cut -f1)
duration=$SECONDS
echo "Built ./podracer ($size)"
echo "Took $((duration / 60)):$((duration % 60))"
