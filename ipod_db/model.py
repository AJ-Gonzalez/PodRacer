"""In-memory model of an iPod library.

Pure data classes, no I/O. The iTunesDB codec translates between these
objects and the binary format (see parser.py / writer.py). A library is
seeded from the DB on the device; every mutation happens on these objects;
at write time we emit a full fresh DB from them (rebuild-from-state).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The mhit fixed header is this large in every DB the v1 devices write
# (dbversion 0x0c and later). Older DBs (0x9c) exist but are out of scope.
MHIT_HEADER_LEN = 0x248

# First track ID iTunes assigns; libgpod renumbers from here on write.
FIRST_IPOD_ID = 52

# Mac epoch: seconds between 1904-01-01 and 1970-01-01.
MAC_EPOCH_OFFSET = 2082844800


@dataclass(eq=False)
class Track:
    """One song/video on the device. All fields mirror the mhit layout."""

    # -- fixed header fields (all offsets relative to the mhit start) --
    id: int = 0                      # +0x10 device-track id (renumbered on write)
    visible: int = 1                 # +0x14
    filetype_marker: int = 0         # +0x18 four chars, e.g. b"MP3 " (0 = unset)
    type1: int = 0                   # +0x1c
    type2: int = 0                   # +0x1d
    compilation: int = 0             # +0x1e
    rating: int = 0                  # +0x1f
    time_modified: int = 0           # +0x20 mac seconds
    size: int = 0                    # +0x24 bytes
    tracklen: int = 0                # +0x28 milliseconds
    track_nr: int = 0                # +0x2c
    tracks: int = 0                  # +0x30
    year: int = 0                    # +0x34
    bitrate: int = 0                 # +0x38
    samplerate: int = 0              # +0x3c high 16 bits
    samplerate_low: int = 0          # +0x3c low 16 bits
    volume: int = 0                  # +0x40
    starttime: int = 0               # +0x44
    stoptime: int = 0                # +0x48
    soundcheck: int = 0              # +0x4c
    playcount: int = 0               # +0x50
    playcount2: int = 0              # +0x54
    time_played: int = 0             # +0x58 mac seconds
    cd_nr: int = 0                   # +0x5c
    cds: int = 0                     # +0x60
    drm_userid: int = 0              # +0x64
    time_added: int = 0              # +0x68 mac seconds
    bookmark_time: int = 0           # +0x6c
    dbid: int = 0                    # +0x70 64-bit persistent id
    checked: int = 0                 # +0x78
    app_rating: int = 0              # +0x79
    bpm: int = 0                     # +0x7a
    artwork_count: int = 0           # +0x7c
    unk126: int = 0xFFFF             # +0x7e 0xFFFF mp3/aac, 0 uncompressed
    artwork_size: int = 0            # +0x80
    unk132: int = 0                  # +0x84
    samplerate2: float = 0.0         # +0x88
    time_released: int = 0           # +0x8c mac seconds
    unk144: int = 0                  # +0x90
    explicit_flag: int = 0           # +0x92
    unk148: int = 0                  # +0x94
    unk152: int = 0                  # +0x98
    skipcount: int = 0               # +0x9c
    last_skipped: int = 0            # +0xa0 mac seconds
    has_artwork: int = 0             # +0xa4
    skip_when_shuffling: int = 0     # +0xa5
    remember_playback_position: int = 0  # +0xa6
    flag4: int = 0                   # +0xa7
    dbid2: int = 0                   # +0xa8 64-bit
    lyrics_flag: int = 0             # +0xb0
    movie_flag: int = 0              # +0xb1
    mark_unplayed: int = 0x01        # +0xb2
    unk179: int = 0                  # +0xb3
    unk180: int = 0                  # +0xb4
    pregap: int = 0                  # +0xb8
    samplecount: int = 0             # +0xbc 64-bit
    unk196: int = 0                  # +0xc4
    postgap: int = 0                 # +0xc8
    unk204: int = 0                  # +0xcc
    mediatype: int = 0               # +0xd0
    season_nr: int = 0               # +0xd4
    episode_nr: int = 0              # +0xd8
    unk220: int = 0                  # +0xdc
    unk224: int = 0                  # +0xe0
    unk228: int = 0                  # +0xe4
    unk232: int = 0                  # +0xe8
    unk236: int = 0                  # +0xec
    unk240: int = 0                  # +0xf0
    unk244: int = 0                  # +0xf4
    gapless_data: int = 0            # +0xf8
    unk252: int = 0                  # +0xfc
    gapless_track_flag: int = 0      # +0x100
    gapless_album_flag: int = 0      # +0x102
    album_id: int = 0                # +0x11c (renumbered on write)
    artist_id: int = 0               # +0x1dc (renumbered on write)
    composer_id: int = 0             # +0x1f0 (renumbered on write)
    mhii_link: int = 0               # +0x15c artwork link, keep as parsed

    # -- MHOD string fields --
    title: str | None = None
    ipod_path: str | None = None     # iPod_Control:Music:F00:xyz.mp3 (colons)
    album: str | None = None
    artist: str | None = None
    genre: str | None = None
    filetype: str | None = None      # human description, e.g. "MPEG audio file"
    comment: str | None = None
    category: str | None = None
    composer: str | None = None
    grouping: str | None = None
    description: str | None = None
    podcasturl: str | None = None
    podcastrss: str | None = None
    subtitle: str | None = None
    tvshow: str | None = None
    tvepisode: str | None = None
    tvnetwork: str | None = None
    albumartist: str | None = None
    keywords: str | None = None
    sort_artist: str | None = None
    sort_title: str | None = None
    sort_album: str | None = None
    sort_albumartist: str | None = None
    sort_composer: str | None = None
    sort_tvshow: str | None = None

    # The device shows the file name on screen when the title is empty;
    # the master playlist members are matched to files by ipod_path.
    @property
    def display_title(self) -> str:
        return self.title or (self.ipod_path or "").split(":")[-1]


@dataclass
class SPLPref:
    """Settings of a smart playlist (mhod type 50)."""

    liveupdate: int = 1
    checkrules: int = 1
    checklimits: int = 0
    limittype: int = 3
    limitsort: int = 2
    limitvalue: int = 25
    matchcheckedonly: int = 0
    limitsort_opposite: int = 0


@dataclass
class SPLRule:
    """One smart-playlist rule (big-endian SLst block, mhod type 51)."""

    field: int = 0
    action: int = 0
    # String rules carry UTF-16BE text; value rules carry six 64-bit values
    # (from/to value/date/units) plus five 32-bit unknowns.
    string: str | None = None
    fromvalue: int = 0
    fromdate: int = 0
    fromunits: int = 0
    tovalue: int = 0
    todate: int = 0
    tounits: int = 0
    unk052: int = 0
    unk056: int = 0
    unk060: int = 0
    unk064: int = 0
    unk068: int = 0


@dataclass
class SPLRules:
    """The SLst wrapper of a smart playlist's rules."""

    unk004: int = 0
    match_operator: int = 0
    rules: list[SPLRule] = field(default_factory=list)


# Smart-playlist action/field meaning tables live with the parser; the
# device regenerates these playlists anyway, we only carry them over.
# Known actions (from libgpod):
#   1024      = "is" / equals
#   33555456  = "is not" / not equals
SPL_ACTION_IS = 1024
SPL_ACTION_IS_NOT = 33555456


@dataclass(eq=False)
class Playlist:
    name: str
    # 1 = master playlist ("this iPod"), 0 = ordinary
    ptype: int = 0
    id: int = 0                      # 64-bit, random when new
    flag1: int = 0
    flag2: int = 0
    flag3: int = 0
    timestamp: int = 0               # mac seconds
    podcastflag: int = 0
    sortorder: int = 0
    sortdescending: int = 0
    is_spl: bool = False
    splpref: SPLPref | None = None
    splrules: SPLRules | None = None
    # mhsd5 playlists carry a type byte (Music=1, Films=2, ...)
    mhsd5_type: int = 0
    members: list[Track] = field(default_factory=list)

    @property
    def is_mpl(self) -> bool:
        return self.ptype == 1


@dataclass(eq=False)
class Library:
    """Everything the codec keeps about a device library."""

    # -- mhbd header --
    version: int = 0x30
    compressed: int = 1              # 1 = plain, 2 = zlib (iPhone only)
    db_id: int = 0                   # 64-bit
    platform: int = 1                # 1 = macOS, 2 = Windows
    unk_0x22: int = 0
    id_0x24: int = 0                 # 64-bit, echoed into every mhit
    lang: int = 0
    pid: int = 0                     # 64-bit library persistent id
    unk_0x50: int = 0
    unk_0x54: int = 0
    tzoffset: int = 0
    audio_language: int = 0
    subtitle_language: int = 0
    unk_0xa4: int = 0
    unk_0xa6: int = 0
    unk_0xa8: int = 0

    genius_cuid: str | None = None

    tracks: list[Track] = field(default_factory=list)
    playlists: list[Playlist] = field(default_factory=list)   # MPL first
    mhsd5_playlists: list[Playlist] = field(default_factory=list)

    def master_playlist(self) -> Playlist | None:
        for pl in self.playlists:
            if pl.is_mpl:
                return pl
        return None
