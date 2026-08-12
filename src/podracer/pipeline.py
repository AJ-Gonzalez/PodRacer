"""Copy/transcode pipeline: source file -> track on the iPod.

`add_file()` is the whole add operation in one call: read tags
(ffprobe), check duplicates (provenance sidecar), copy native formats
verbatim or transcode to MP3 (embedded art recompressed), place the
file under iPod_Control/Music, build the Track, append it to the
library state, and record its digest in the sidecar. The DB write
happens later, at eject.

The device does not care about file names — only DB correctness — so
names are short random codes in F00..F3F, like iTunes' own scheme.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import string
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from podracer_db.model import MAC_EPOCH_OFFSET, Track

from .provenance import ProvenanceDB, check_duplicate

# Extensions the nano 3G plays as-is; everything else is transcoded.
# Video (.mp4/.m4v) is copied verbatim, never transcoded — only H.264
# Baseline / MPEG-4 Simple Profile up to 640x480 actually plays on the
# nano 3G, so incompatible files are rejected with a reason instead of
# copied (see video_compatible()).
NATIVE_EXTENSIONS = frozenset({
    ".mp3", ".m4a", ".aac", ".wav", ".aiff", ".aif",
    ".mp4", ".m4v",
})

# Containers the nano 3G shows in its Videos section.
VIDEO_EXTENSIONS = frozenset({".mp4", ".m4v"})

# Transcode target: MP3 256 kbps (user decision 2026-08-11: the AAC
# container also needed a faststart moov; MP3 avoids the whole class).
# Embedded cover art is recompressed, never copied: the nano 3G's ID3
# parser chokes on large tags (a 1400x1400 FLAC cover survives as an
# ~890 KiB APIC; the device lists the track but refuses to play it).
# iTunes recompresses art to 600x600 for the same reason; the nano
# displays at 132px, so 600px is already oversampled. The '?' maps make
# the art stream optional, so art-less sources still transcode.
TRANSCODE_ARGS = [
    "ffmpeg", "-nostdin", "-y",
    "-i", "{src}",
    "-map", "0:a?", "-map", "0:v?",
    "-c:a", "libmp3lame", "-b:a", "256k",
    "-c:v", "mjpeg", "-q:v", "8",
    "-vf", "scale=600:600:force_original_aspect_ratio=decrease",
    "-id3v2_version", "3",
    # Explicit muxer: the temp file name has a .podracer-tmp suffix,
    # so ffmpeg cannot infer the format from the extension.
    "-f", "mp3",
    "{dst}",
]

# The DB carries the encoded bitrate; hardcoded so it cannot drift
# from the -b:a value above.
TRANSCODE_BITRATE = 256_000

# Everything we will copy or transcode when files/folders are dropped:
# music (native + transcodeable) plus video the nano can play.
ACCEPTED_EXTENSIONS = NATIVE_EXTENSIONS | frozenset(
    {".flac", ".ogg", ".opus", ".wma", ".ape", ".m4b"}
)


def collect_audio(sources: list[Path]) -> list[Path]:
    """Expand a drop (files and folders) to a sorted media list.

    Folders are walked recursively; non-music/non-video files are
    ignored (album covers, NFOs, executables); the result is
    deduplicated and sorted so the add order is stable.
    """
    found: set[Path] = set()
    for source in sources:
        if source.is_dir():
            found.update(
                p for p in source.rglob("*")
                if p.is_file() and p.suffix.lower() in ACCEPTED_EXTENSIONS
            )
        elif source.is_file() and source.suffix.lower() in ACCEPTED_EXTENSIONS:
            found.add(source)
    return sorted(found, key=lambda p: str(p).casefold())


# Human filetype strings, matching what iTunes writes in the DB.
_FILETYPE_NAMES = {
    "mp3": "MPEG audio file",
    "m4a": "AAC audio file",
    "aac": "AAC audio file",
    "wav": "WAV audio file",
    "aiff": "AIFF audio file",
    "aif": "AIFF audio file",
    "mp4": "MPEG-4 video file",
    "m4v": "MPEG-4 video file",
}

_MARKERS = {
    ".mp3": b"MP3 ",
    ".m4a": b"M4A ",
    ".wav": b"WAV ",
    ".aiff": b"AIF ",
    ".aif": b"AIF ",
    ".mp4": b"M4V ",
    ".m4v": b"M4V ",
}


class PipelineError(RuntimeError):
    """A source file could not be read, tagged, or copied."""


@dataclass
class AddResult:
    track: Track | None = None
    # "added" | "content" | "metadata" | "error"
    status: str = "added"
    message: str = ""


def needs_transcode(path: str | Path) -> bool:
    return Path(path).suffix.lower() not in NATIVE_EXTENSIONS


# The nano 3G plays H.264 Baseline / MPEG-4 Simple Profile, capped at
# 640x480@30fps and 2.5 Mbps. Anything else would list in the library
# but never play (the same failure class as the big-APIC bug), so it is
# rejected at add time with a reason. Conservative on purpose: profile
# support beyond the spec is unverified on this hardware.
_VIDEO_PROFILES = {
    "h264": {"Baseline", "Constrained Baseline"},
    "mpeg4": {"Simple"},
}
_VIDEO_MAX_W = 640
_VIDEO_MAX_H = 480
_VIDEO_MAX_BPS = 2_500_000


def video_compatible(path: str | Path) -> str | None:
    """Why a video will not play on the nano 3G, or None if it will."""
    path = Path(path)
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_streams", str(path)],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        return f"ffprobe failed: {exc}"
    info = json.loads(proc.stdout)
    video = next(
        (s for s in info.get("streams", [])
         if s.get("codec_type") == "video"),
        None,
    )
    if video is None:
        return "no video stream"
    codec = video.get("codec_name", "")
    profile = video.get("profile") or ""
    if codec not in _VIDEO_PROFILES:
        return f"codec {codec} — the nano 3G plays H.264 or MPEG-4 video"
    if profile and not any(
        allowed in profile for allowed in _VIDEO_PROFILES[codec]
    ):
        return (
            f"{codec} profile {profile} — the nano 3G needs "
            f"{sorted(_VIDEO_PROFILES[codec])}"
        )
    width = int(video.get("width", 0) or 0)
    height = int(video.get("height", 0) or 0)
    if width > _VIDEO_MAX_W or height > _VIDEO_MAX_H:
        return f"{width}x{height} — the nano 3G caps video at 640x480"
    bitrate = int(video.get("bit_rate", 0) or 0)
    if bitrate > _VIDEO_MAX_BPS:
        return f"{bitrate / 1e6:.1f} Mbps video — the nano 3G caps at 2.5 Mbps"
    return None


def read_tags(path: str | Path) -> Track:
    """Tags + duration + bitrate of a source file, via ffprobe."""
    path = Path(path)
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        raise PipelineError(f"ffprobe failed on {path}: {exc}") from exc

    info = json.loads(proc.stdout)
    fmt = info.get("format", {})
    tags = fmt.get("tags", {}) or {}

    track = Track(
        title=tags.get("title"),
        artist=tags.get("artist"),
        album=tags.get("album"),
        genre=tags.get("genre"),
        year=_year_from(tags.get("date")) or _int_or(tags.get("year")),
        comment=tags.get("comment"),
        tracklen=int(float(fmt.get("duration", 0)) * 1000),
        bitrate=_int_or(fmt.get("bit_rate")),
    )
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "audio":
            track.samplerate = _int_or(stream.get("sample_rate"))
            break
    if not track.title:
        track.title = path.stem
    return track


def _int_or(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _year_from(value: object) -> int:
    """'2001-01-01' style dates -> the year."""
    text = str(value)
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return 0


def ipod_filename(extension: str, used: set[str]) -> str:
    """A unique short name for the device: 4 random chars + extension."""
    alphabet = string.ascii_uppercase + string.digits
    while True:
        name = "".join(random.choices(alphabet, k=4)) + extension
        if name not in used:
            used.add(name)
            return name


def ipod_path_parts(ipod_path: str) -> tuple[str, ...]:
    """The colon-path elements, ignoring the leading root marker.

    Device paths are root-anchored (':iPod_Control:Music:F00:x.mp3');
    the empty first element is the marker, not a directory.
    """
    parts = ipod_path.split(":")
    if parts and parts[0] == "":
        parts = parts[1:]
    return tuple(parts)


def copy_or_transcode(source: str | Path, dest: Path) -> None:
    """Copy verbatim or transcode to MP3, atomically (temp + rename)."""
    source = Path(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".podracer-tmp")
    if needs_transcode(source):
        args = [a.format(src=source, dst=tmp) for a in TRANSCODE_ARGS]
        try:
            subprocess.run(args, capture_output=True, text=True,
                           check=True, timeout=1800)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            tmp.unlink(missing_ok=True)
            raise PipelineError(f"ffmpeg failed on {source}: {exc}") from exc
    else:
        shutil.copyfile(source, tmp)
    with open(tmp, "rb") as fh:
        os.fsync(fh.fileno())
    tmp.rename(dest)


def add_file(
    library_tracks: list[Track],
    db: ProvenanceDB,
    source: str | Path,
    ipod_dir: Path,
) -> AddResult:
    """Stage one source file onto the iPod tree; caller writes the DB.

    @library_tracks: current library state; mutated by appending the
    new track on success (also seeds the used-name set). @ipod_dir:
    the device's iPod_Control/Music directory.
    """
    source = Path(source)
    try:
        probe = read_tags(source)
    except PipelineError as exc:
        return AddResult(status="error", message=str(exc))

    if source.suffix.lower() in VIDEO_EXTENSIONS:
        problem = video_compatible(source)
        if problem is not None:
            return AddResult(
                status="error",
                message=f"{source.name}: {problem}",
            )

    duplicate = check_duplicate(db, source, probe, library_tracks)
    if duplicate is not None:
        return AddResult(status=duplicate, message=str(source))

    extension = source.suffix.lower()
    if needs_transcode(source):
        extension = ".mp3"

    used_names = {
        t.ipod_path.rsplit(":", 1)[-1]
        for t in library_tracks
        if t.ipod_path
    }
    name = ipod_filename(extension, used_names)
    folder = "F" + format(random.randrange(0, 0x40), "02X")
    # Device paths are root-anchored: the leading colon is the root
    # marker. Without it the firmware resolves the path relative and
    # cannot find the file (track lists, but won't play).
    ipod_path = f":iPod_Control:Music:{folder}:{name}"
    dest = ipod_dir / folder / name

    try:
        copy_or_transcode(source, dest)
    except PipelineError as exc:
        return AddResult(status="error", message=str(exc))

    track = probe
    if needs_transcode(source):
        # probe reads the source's bitrate (e.g. a FLAC's 1.8 Mbps);
        # the DB must carry what we actually encoded.
        track.bitrate = TRANSCODE_BITRATE
    track.ipod_path = ipod_path
    track.filetype = _FILETYPE_NAMES.get(
        Path(name).suffix.lstrip("."), "MPEG audio file"
    )
    track.filetype_marker = int.from_bytes(
        _MARKERS.get(Path(name).suffix, b"\x00\x00\x00\x00"), "little"
    )
    # Video lands in the device's Videos section (mediatype 8 = movie;
    # audio is 1). Boot-test pending on the exact section.
    track.mediatype = 8 if source.suffix.lower() in VIDEO_EXTENSIONS else 1
    track.size = dest.stat().st_size
    track.unk126 = 0xFFFF
    # Every working writer stamps these: unique persistent id (dbid2
    # mirrors it), mac-epoch add/modify times, samplerate as float.
    while True:
        dbid = random.getrandbits(64)
        if dbid and all(t.dbid != dbid for t in library_tracks):
            break
    mac_now = int(time.time()) + MAC_EPOCH_OFFSET
    track.dbid = dbid
    track.dbid2 = dbid
    track.time_added = mac_now
    track.time_modified = mac_now
    track.samplerate2 = float(track.samplerate or 0)

    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    db.remember_device_file(ipod_path, digest)
    library_tracks.append(track)
    return AddResult(track=track, status="added", message=str(source))
