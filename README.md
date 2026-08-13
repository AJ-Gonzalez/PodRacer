# PodRacer
<table>
<tr>
<td>

<img src="src/podracer/assets/podracer_icon.png" width="128" height="128" alt="PodRacer logo">
</td>
<td>

<pre style="font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-style: italic;">
 ____           _ ____                     
|  _ \ ___   __| |  _ \ __ _  ___ ___ _ __ 
| |_) / _ \ / _` | |_) / _` |/ __/ _ \ '__|
|  __/ (_) | (_| |  _ < (_| | (_|  __/ |   
|_|   \___/ \__,_|_| \_\__,_|\___\___|_|  
</pre>

</td>
</tr>
</table>
Transfer music to an iPod from Linux without iTunes. 

**Plug in the iPod, open PodRacer, drag music over.**

Midnight-commander-style two-pane UI: browse your music folder on the left, see what is on the iPod on the right. Manual sync, automatic duplicate avoidance, auto-transcode via ffmpeg.

Targets the classic iTunesDB device family first: iPod nano 3G (the original target) plus nano 1-3G and classic 1-5.5G.

## Themes

<img src="mockups/contact-sheet.png" width="800" alt="Six PodRacer themes: Grey Moonlight, Frutiger Aero, Aqua, Dark Aqua, Minty Forest, Lilac Love">

Six of the thirteen built-in themes, rendered in demo mode (synthetic data only). Run `./podracer --demo` to preview any theme with a sample library — nothing real is touched.

## Run it

- From the repo: `scripts/build_onefile.sh` produces `./podracer` (one file, ~90 MB). Symlink it into your PATH: `ln -s "$PWD/podracer" ~/.local/bin/podracer`. Launch from a terminal or double-click.
- From source: `PYTHONPATH=src python3 -m podracer.main`

## Development

- Python 3.13, PySide6 (Qt6) — UI (packages live under `src/`)
- `podracer_db` — pure-stdlib iTunesDB codec
- ffmpeg — tagging + transcoding to MP3
- `scripts/extract_fixtures.py` — pull the DB + sample tracks from a real iPod for tests
- Tests: `python3 -m unittest discover -s tests -t . -v` (stdlib only)


