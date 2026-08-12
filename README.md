# PodRacer

Transfer music to an iPod from Linux without iTunes. 

**Plug in the iPod, open PodRacer, drag music over.**

Midnight-commander-style two-pane UI: browse your music folder on the left, see what is on the iPod on the right. Manual sync, automatic duplicate avoidance, auto-transcode via ffmpeg.

Targets the classic iTunesDB device family first: iPod nano 3G (the original target) plus nano 1-3G and classic 1-5.5G.

## Run it

- From the repo: `scripts/build_onefile.sh` produces `./podracer` (one file, ~90 MB). Symlink it into your PATH: `ln -s "$PWD/podracer" ~/.local/bin/podracer`. Launch from a terminal or double-click.
- From source: `PYTHONPATH=src python3 -m podracer.main`

## Development

- Python 3.13, PySide6 (Qt6) — UI (packages live under `src/`)
- `podracer_db` — pure-stdlib iTunesDB codec
- ffmpeg — tagging + transcoding to AAC
- `scripts/extract_fixtures.py` — pull the DB + sample tracks from a real iPod for tests
- Tests: `python3 -m unittest discover -s tests -t . -v` (stdlib only)


