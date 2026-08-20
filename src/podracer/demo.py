"""Demo mode: a synthetic library and music tree for showcasing.

`podracer --demo` renders the whole UI with invented data so screenshots
and theme previews never touch the user's real library. Every name
here is fabricated on purpose — nothing maps to a real artist or album.
"""

from __future__ import annotations

import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from podracer_db import write_db
from podracer_db.model import Library, Playlist, Track

from .device import IPod

GUID = "0011223344556677"

# Invented catalog: artist -> [(album, year, [titles])]
_CATALOG: dict[str, tuple[str, int, list[str]]] = {
    "Neon Harbor": ("Afterglow Boulevard", 2021, [
        "Neon Tides", "Streetlight Static", "Harbor Lights",
        "Glass Highway", "Midnight Commute",
    ]),
    "The Paper Satellites": ("Night Covers", 2019, [
        "Fold Me Away", "Constellation Paper", "Low Orbit",
        "Received Signal", "Reentry",
    ]),
    "Mono Motel": ("Vacancy", 2022, [
        "No Vacancy", "Room 404", "Checkout Time",
        "The Fern Bar", "Receipts",
    ]),
    "Cinder & Sage": ("Ash Bloom", 2020, [
        "Smoke Garden", "Tinderbox", "Ember Phase",
        "Wildfire Waltz", "Cold Campfire",
    ]),
    "Radio Telescope": ("Signal to Noise", 2018, [
        "Parabolic", "Gain Control", "Static Kiss",
        "Aperture", "Quiet Spectrum",
    ]),
    "June Arcade": ("Quarter Life", 2023, [
        "Insert Coin", "High Score", "Attract Mode",
        "Bonus Stage", "Game Over Screen",
    ]),
    "Velvet Orchard": ("Ripe", 2017, [
        "Peach Fuzz", "Orchard Keeper", "Sweet Rot",
        "Picking Season", "Jam Session",
    ]),
    "The Static Owls": ("Hoot Hoot Hustle", 2024, [
        "Night Shift", "Wingbeat", "Campus Trees",
        "Who Cooks For You", "First Light Flight",
    ]),
}


def demo_library() -> Library:
    """A fabricated library: ~40 tracks across eight invented albums."""
    tracks: list[Track] = []
    dbid = 0x1000
    for album_index, (artist, (album, year, titles)) in enumerate(
        sorted(_CATALOG.items())
    ):
        for track_nr, title in enumerate(titles, start=1):
            track = Track(
                title=title,
                artist=artist,
                album=album,
                genre="Demo",
                year=year,
                tracklen=3 * 60_000 + track_nr * 7_000,
                track_nr=track_nr,
                bitrate=256_000,
                samplerate=44100,
                size=8_000_000 + album_index * 1_000_000 + track_nr * 37_000,
                dbid=dbid,
                dbid2=dbid,
                ipod_path=(
                    f":iPod_Control:Music:F{album_index:02X}:"
                    f"D{track_nr:02d}{album_index:02X}.mp3"
                ),
                filetype="MPEG audio file",
            )
            track.filetype_marker = int.from_bytes(b"MP3 ", "little")
            tracks.append(track)
            dbid += 1
    lib = Library(tracks=tracks)
    lib.playlists = [Playlist(name="Demo Nano", ptype=1, id=0x1234,
                              members=tracks)]
    return lib


def demo_music_tree(root: Path) -> Path:
    """A fake Artist/Album/01 - Title.mp3 tree matching demo_library().

    The files are real (silent, tagged) MP3s so the demo covers the
    whole add flow — drag a folder onto the library, watch it probe,
    copy, and appear as tagged tracks. Without ffmpeg the files fall
    back to empty placeholders so the UI-only showcase still boots.
    """
    music = root / "Music"
    with ThreadPoolExecutor(max_workers=6) as pool:
        for artist, (album, year, titles) in _CATALOG.items():
            album_dir = music / artist / album
            album_dir.mkdir(parents=True, exist_ok=True)
            for n, title in enumerate(titles, start=1):
                # ffmpeg spawns are process-bound; the pool cuts the
                # ~5 s sequential build to ~1.5 s. _write_demo_mp3
                # swallows its own errors, so nothing can raise here.
                pool.submit(
                    _write_demo_mp3,
                    album_dir / f"{n:02d} - {title}.mp3",
                    artist, album, title, n, year,
                )
    return music


def _write_demo_mp3(
    dest: Path, artist: str, album: str, title: str,
    track_nr: int, year: int,
) -> None:
    """A real, probe-able silent MP3 carrying the catalog tags.

    One ffmpeg call per track (~0.15 s, ~1.7 KB each). Failure is
    silent: without ffmpeg the demo degrades to the old empty
    placeholders rather than refusing to start.
    """
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error",
             "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-t", "0.3", "-c:a", "libmp3lame", "-q:a", "9",
             "-metadata", f"title={title}",
             "-metadata", f"artist={artist}",
             "-metadata", f"album={album}",
             "-metadata", "genre=Demo",
             "-metadata", f"track={track_nr}",
             "-metadata", f"date={year}",
             str(dest)],
            capture_output=True, check=True, timeout=60,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        dest.write_bytes(b"")


def build_demo(root: Path | None = None) -> tuple[IPod, Path]:
    """A fake mounted iPod (seeded with demo_library) + the demo tree."""
    root = root or Path(tempfile.mkdtemp(prefix="podracer-demo-"))
    ipod_dir = root / "DEMO"
    (ipod_dir / "iPod_Control" / "iTunes").mkdir(parents=True)
    (ipod_dir / "iPod_Control" / "Music").mkdir(parents=True)
    (ipod_dir / "iPod_Control" / "iTunes" / "iTunesDB").write_bytes(
        write_db(demo_library(), firewire_guid=GUID)
    )
    ipod = IPod(mountpoint=ipod_dir, label="DEMO", block_device="sdb1",
                guid=GUID, serial="DEMO00000000", family_id=12, db_version=3)
    return ipod, demo_music_tree(root)
