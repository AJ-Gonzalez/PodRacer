# PodRacer

Transfer music to an iPod from Linux — no iTunes. Plug in the iPod, open PodRacer, drag music over. That is the whole manual.

Midnight-commander-style two-pane UI: browse your music folder on the left, see what is on the iPod on the right. Manual sync, automatic duplicate avoidance, auto-transcode via ffmpeg.

Targets the classic iTunesDB device family first: iPod nano 3G (the original target) plus nano 1-3G and classic 1-5.5G.

## Status

Experimental. The iTunesDB codec (parse + write, verified against a real nano 3G) is done — see ROADMAP.md. Sync core and UI are next.

## Development

- Python 3.13, PySide6 (Qt6) — UI
- `podracer_db` — pure-stdlib iTunesDB codec
- ffmpeg — transcoding to AAC
- `scripts/extract_fixtures.py` — pull the DB + sample tracks from a real iPod for tests
- Tests: `python3 -m unittest discover -s tests -v` (stdlib only)

