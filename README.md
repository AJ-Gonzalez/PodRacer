<h1>
<img src="src/podracer/assets/podracer_icon.png" width="48" height="48" alt="PodRacer logo" style="vertical-align: middle;">
PodRacer
</h1>

<pre style="font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-style: italic;">
 ____           _ ____                     
|  _ \ ___   __| |  _ \ __ _  ___ ___ _ __ 
| |_) / _ \ / _` | |_) / _` |/ __/ _ \ '__|
|  __/ (_) | (_| |  _ < (_| | (_|  __/ |   
|_|   \___/ \__,_|_| \_\__,_|\___\___|_|  
</pre>

Transfer music to an iPod from Linux without iTunes. 

**Plug in the iPod, open PodRacer, drag music over.**

Midnight-commander-style two-pane UI: browse your music folder on the left, see what is on the iPod on the right. Manual sync, automatic duplicate avoidance, auto-transcode via ffmpeg.

## Compatibility

| Device generation | Supported? | Tested on Physical Hardware? |
| --- | --- | --- |
| iPod nano 3G | Yes | Yes |
| iPod nano 1G–2G | Yes | No |
| iPod classic 1G–5.5G | Yes | No |
| iPod mini | Yes | No |
| iPod nano 4G+ | No | No |
| iPod classic 6G/7G | No | No |
| iPod shuffle | No | No |
| iPod touch | No | No |

nano 4G+ and classic 6G/7G (iTunesSD format) are planned.

## Themes

<img src="mockups/contact-sheet.png" width="800" alt="Six PodRacer themes: Grey Moonlight, Frutiger Aero, Aqua, Dark Aqua, Minty Forest, Lilac Love">

Six of the thirteen built-in themes, rendered in demo mode (synthetic data only). Run `./podracer --demo` to preview any theme with a mock library, nothing real is touched.

## Run it

- From PyPI: `pipx install podracer_mapple` (or `pip install podracer_mapple` inside a venv), then launch `podracer` from a terminal.
- From the repo: `scripts/build_onefile.sh` produces `./podracer` (one file, ~90 MB). Symlink it into your PATH: `ln -s "$PWD/podracer" ~/.local/bin/podracer`. Launch from a terminal or double-click.
- From source: `PYTHONPATH=src python3 -m podracer.main`

> pip installs the app only. It still needs `ffmpeg` (tag reading + transcoding) and `udisksctl` (auto-mounting) on your system.

Plug in the iPod, and that's the whole setup. Enjoy the click of the wheel.

## The podracer_db library

PodRacer is built on a small, standalone library: `podracer_db` parses and writes the classic iTunesDB format, the database on nano 1G–3G, classic 1G–5.5G, and mini. Pure stdlib, zero dependencies, no Qt.

It is also handy on its own. Point it at the `iTunesDB` file from a device or a backup and you get every track with its tags, play counts, and ratings, plus the playlists, smart-playlist rules included:

```python
from pathlib import Path
from podracer_db import parse_db, write_db

lib = parse_db(Path("iTunesDB").read_bytes())
for track in lib.tracks:
    print(track.artist or "Unknown", "-", track.display_title)

# And back the other way: serialize the library to a valid DB,
# hash58 checksum included, ready for a device to boot.
db_bytes = write_db(lib, firewire_guid="0011223344556677")
```

The write side is hardware-verified: a PodRacer-written DB boots on the real nano 3G with its full library, and the codec round-trips the device's own DB byte-for-byte. The codec is the heart of the app, but it works just as happily without a UI.

## Development

- Python 3.13, PySide6 (Qt6) UI in `src/`
- `podracer_db` in `packages/podracer_db/` (its own PyPI dist, see above)
- ffmpeg for tagging and transcoding to MP3
- `scripts/extract_fixtures.py` pulls the DB and sample tracks from a real iPod for tests
- Tests: `python3 -m unittest discover -s tests -t . -v` (stdlib only)


