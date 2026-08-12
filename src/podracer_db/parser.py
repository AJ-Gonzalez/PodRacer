"""iTunesDB parser: bytes -> Library.

Implements the classic format used by nano 1-3G, classic 1-5.5G and mini
(dbversion 0x0c+; the mhit header is 0x248 bytes). Little-endian only —
every v1 device writes little-endian. The reverse-endian (pre-2003) and
iTunesSD (nano 4G+) families are out of scope and rejected loudly.

Layout (all lengths little-endian):

    mhbd  header(244)                  [db metadata]
    mhsd  header(96)                   section; type 1 = tracks,
                                       2/3 = playlists, 4 = albums,
                                       5 = smart playlists, 6/10 = empty,
                                       8 = artists, 9 = genius
      mhlt  header(92) + count         (tracks)
        mhit  header(0x248) + mhod*    (one per track)
      mhlp  header(92) + count         (playlists)
        mhyp  header(108) + mhod* + mhip*   (one per playlist)
          mhip  header(76) + mhod(44)  (one per member)

Sections are walked by their total-length field; unknown/derivable
chunks are skipped by size, so extra fields Apple adds later are
tolerated.
"""

from __future__ import annotations

from .binary import FormatError, Reader
from .model import (
    Library,
    Playlist,
    SPLPref,
    SPLRule,
    SPLRules,
    Track,
)

MHBD_HEADER = 244
MHSD_HEADER = 96
MHLT_HEADER = 92
MHIT_HEADER = 0x248
MHLP_HEADER = 92
MHYP_HEADER = 108
MHP_HEADER = 76
MHOD_HEADER = 24

# MHOD types (enum MHOD_ID in libgpod)
MHOD_TITLE = 1
MHOD_PATH = 2
MHOD_ALBUM = 3
MHOD_ARTIST = 4
MHOD_GENRE = 5
MHOD_FILETYPE = 6
MHOD_COMMENT = 8
MHOD_CATEGORY = 9
MHOD_COMPOSER = 12
MHOD_GROUPING = 13
MHOD_DESCRIPTION = 14
MHOD_PODCASTURL = 15
MHOD_PODCASTRSS = 16
MHOD_SUBTITLE = 18
MHOD_TVSHOW = 19
MHOD_TVEPISODE = 20
MHOD_TVNETWORK = 21
MHOD_ALBUMARTIST = 22
MHOD_KEYWORDS = 24
MHOD_SORT_ARTIST = 23
MHOD_SORT_TITLE = 27
MHOD_SORT_ALBUM = 28
MHOD_SORT_ALBUMARTIST = 29
MHOD_SORT_COMPOSER = 30
MHOD_SORT_TVSHOW = 31
MHOD_SPLPREF = 50
MHOD_SPLRULES = 51
MHOD_LIBPLAYLISTINDEX = 52
MHOD_LIBPLAYLISTJUMPTABLE = 53
MHOD_PLAYLIST = 100

# String MHODs that map onto Track fields.
_STRING_MHODS: dict[int, str] = {
    MHOD_TITLE: "title",
    MHOD_PATH: "ipod_path",
    MHOD_ALBUM: "album",
    MHOD_ARTIST: "artist",
    MHOD_GENRE: "genre",
    MHOD_FILETYPE: "filetype",
    MHOD_COMMENT: "comment",
    MHOD_CATEGORY: "category",
    MHOD_COMPOSER: "composer",
    MHOD_GROUPING: "grouping",
    MHOD_DESCRIPTION: "description",
    MHOD_PODCASTURL: "podcasturl",
    MHOD_PODCASTRSS: "podcastrss",
    MHOD_SUBTITLE: "subtitle",
    MHOD_TVSHOW: "tvshow",
    MHOD_TVEPISODE: "tvepisode",
    MHOD_TVNETWORK: "tvnetwork",
    MHOD_ALBUMARTIST: "albumartist",
    MHOD_KEYWORDS: "keywords",
    MHOD_SORT_ARTIST: "sort_artist",
    MHOD_SORT_TITLE: "sort_title",
    MHOD_SORT_ALBUM: "sort_album",
    MHOD_SORT_ALBUMARTIST: "sort_albumartist",
    MHOD_SORT_COMPOSER: "sort_composer",
    MHOD_SORT_TVSHOW: "sort_tvshow",
}

MHOD_ALBUM_ALBUM = 200       # mhia child: album name
MHOD_ALBUM_ARTIST = 201      # mhia child: album artist
MHOD_ALBUM_SORT_ARTIST = 202 # mhia child: sort key
MHOD_ALBUM_ARTIST_MHII = 300 # mhii child: artist name

# Podcast URL/RSS mhods carry a raw string (no length prefix).
_RAW_STRING_MHODS = frozenset({MHOD_PODCASTURL, MHOD_PODCASTRSS})


def parse_db(data: bytes) -> Library:
    """Parse a classic iTunesDB into a Library. Raises FormatError."""
    r = Reader(data)

    # --- mhbd ---
    r.magic(b"mhbd", "database header")
    header_len = r.u32()
    if header_len < MHBD_HEADER:
        raise FormatError(
            f"mhbd header too small ({header_len} < {MHBD_HEADER}); "
            "this is not a classic-format DB (iTunesSD device?)"
        )
    r.u32()  # total db size (informational; we trust the file length)
    lib = Library(
        compressed=r.u32(),
        version=r.u32(),
    )
    r.u32()  # number of mhsd children
    lib.db_id = r.u64()
    lib.platform = r.u16()
    lib.unk_0x22 = r.u16()
    lib.id_0x24 = r.u64()
    r.u32()          # unk_0x2c
    r.u16()          # hashing scheme (0x58 with a hash58, 0 otherwise)
    r.skip(20)       # unk_0x32
    lib.lang = r.u16()
    lib.pid = r.u64()
    lib.unk_0x50 = r.u32()
    lib.unk_0x54 = r.u32()
    r.skip(20)       # hash58
    lib.tzoffset = r.u32()
    r.u16()          # checksum type selector
    r.skip(46)       # hash72 slot
    lib.audio_language = r.u16()
    lib.subtitle_language = r.u16()
    lib.unk_0xa4 = r.u16()
    lib.unk_0xa6 = r.u16()
    lib.unk_0xa8 = r.u16()
    # align byte + hashAB slot + padding complete the fixed 244-byte header.
    r.skip(header_len - 170)

    # --- sections ---
    tracks_by_id: dict[int, Track] = {}
    mhsd_types: dict[int, list[Playlist]] = {2: [], 3: [], 5: []}
    while r.pos < len(r.data):
        section_start = r.pos  # the 'mhsd' magic starts here
        r.magic(b"mhsd", "section")
        sec_hdr = r.u32()
        sec_total = r.u32()
        sec_type = r.u32()
        if sec_hdr != MHSD_HEADER:
            raise FormatError(f"unexpected mhsd header size {sec_hdr}")
        if sec_total < MHSD_HEADER or section_start + sec_total > len(r.data):
            raise FormatError(f"mhsd section overruns file at 0x{section_start:x}")
        # Body starts after the 96-byte header; the first 16 of those
        # (magic + three u32) are already consumed.
        body = r.data[section_start + MHSD_HEADER : section_start + sec_total]
        r.skip(sec_total - 16)     # magic + 3 u32 already consumed

        if sec_type == 1:
            tracks_by_id = _parse_tracks(body, tracks_by_id, lib.tracks)
        elif sec_type in (2, 3, 5):
            mhsd_types[sec_type].extend(
                _parse_playlists(body, tracks_by_id, mhsd5=sec_type == 5)
            )
        elif sec_type == 9:
            lib.genius_cuid = _parse_genius(body)
        # types 4, 6, 8, 10: regenerated at write time; skip.

    lib.playlists = _merge_playlist_sections(mhsd_types)
    lib.mhsd5_playlists = mhsd_types[5]
    if not lib.master_playlist():
        raise FormatError("no master playlist found in DB")
    return lib


def _parse_tracks(
    body: bytes, tracks_by_id: dict[int, Track], tracks_out: list[Track]
) -> dict[int, Track]:
    r = Reader(body)
    r.magic(b"mhlt", "track list")
    if r.u32() != MHLT_HEADER:
        raise FormatError("unexpected mhlt header size")
    count = r.u32()
    r.skip(MHLT_HEADER - 12)
    for _ in range(count):
        chunk = r.pos  # chunk start (magic not yet consumed)  # mhit start
        r.magic(b"mhit", "track")
        hdr = r.u32()
        if hdr < MHIT_HEADER:
            raise FormatError(f"mhit header too small ({hdr})")
        total = r.u32()
        mhod_count = r.u32()
        if total < hdr or chunk + total > len(r.data):
            raise FormatError("mhit overruns its section")
        track = _parse_mhit_fixed(r)
        _parse_mhod_strings(r.data[r.pos : chunk + total], mhod_count, track)
        r.skip(total - hdr)
        tracks_by_id[track.id] = track
        tracks_out.append(track)
    return tracks_by_id


def _parse_mhit_fixed(r: Reader) -> Track:
    """Read the 0x248-byte fixed mhit header (reader starts at +0x10)."""
    t = Track()
    t.id = r.u32()                  # +0x10
    t.visible = r.u32()             # +0x14
    t.filetype_marker = int.from_bytes(r.bytes(4), "little")  # +0x18
    t.type1 = r.u8()                # +0x1c
    t.type2 = r.u8()
    t.compilation = r.u8()
    t.rating = r.u8()
    t.time_modified = r.u32()       # +0x20
    t.size = r.u32()                # +0x24
    t.tracklen = r.u32()            # +0x28
    t.track_nr = r.u32()            # +0x2c
    t.tracks = r.u32()              # +0x30
    t.year = r.u32()                # +0x34
    t.bitrate = r.u32()             # +0x38
    sr = r.u32()                    # +0x3c
    t.samplerate = sr >> 16
    t.samplerate_low = sr & 0xFFFF
    t.volume = r.u32()              # +0x40
    t.starttime = r.u32()           # +0x44
    t.stoptime = r.u32()            # +0x48
    t.soundcheck = r.u32()          # +0x4c
    t.playcount = r.u32()           # +0x50
    t.playcount2 = r.u32()          # +0x54
    t.time_played = r.u32()         # +0x58
    t.cd_nr = r.u32()               # +0x5c
    t.cds = r.u32()                 # +0x60
    t.drm_userid = r.u32()          # +0x64
    t.time_added = r.u32()          # +0x68
    t.bookmark_time = r.u32()       # +0x6c
    t.dbid = r.u64()                # +0x70
    t.checked = r.u8()              # +0x78
    t.app_rating = r.u8()           # +0x79
    t.bpm = r.u16()                 # +0x7a
    t.artwork_count = r.u16()       # +0x7c
    t.unk126 = r.u16()              # +0x7e
    t.artwork_size = r.u32()        # +0x80
    t.unk132 = r.u32()              # +0x84
    t.samplerate2 = r.f32()         # +0x88
    t.time_released = r.u32()       # +0x8c
    t.unk144 = r.u16()              # +0x90
    t.explicit_flag = r.u16()       # +0x92
    t.unk148 = r.u32()              # +0x94
    t.unk152 = r.u32()              # +0x98
    t.skipcount = r.u32()           # +0x9c
    t.last_skipped = r.u32()        # +0xa0
    t.has_artwork = r.u8()          # +0xa4
    t.skip_when_shuffling = r.u8()  # +0xa5
    t.remember_playback_position = r.u8()  # +0xa6
    t.flag4 = r.u8()                # +0xa7
    t.dbid2 = r.u64()               # +0xa8
    t.lyrics_flag = r.u8()          # +0xb0
    t.movie_flag = r.u8()           # +0xb1
    t.mark_unplayed = r.u8()        # +0xb2
    t.unk179 = r.u8()               # +0xb3
    t.unk180 = r.u32()              # +0xb4
    t.pregap = r.u32()              # +0xb8
    t.samplecount = r.u64()         # +0xbc
    t.unk196 = r.u32()              # +0xc4
    t.postgap = r.u32()             # +0xc8
    t.unk204 = r.u32()              # +0xcc
    t.mediatype = r.u32()           # +0xd0
    t.season_nr = r.u32()           # +0xd4
    t.episode_nr = r.u32()          # +0xd8
    t.unk220 = r.u32()              # +0xdc
    t.unk224 = r.u32()              # +0xe0
    t.unk228 = r.u32()              # +0xe4
    t.unk232 = r.u32()              # +0xe8
    t.unk236 = r.u32()              # +0xec
    t.unk240 = r.u32()              # +0xf0
    t.unk244 = r.u32()              # +0xf4
    t.gapless_data = r.u32()        # +0xf8
    t.unk252 = r.u32()              # +0xfc
    t.gapless_track_flag = r.u16()  # +0x100
    t.gapless_album_flag = r.u16()  # +0x102
    r.skip(0x160 - 0x104)           # album/composer slots, regenerated on write
    t.mhii_link = r.u32()           # +0x160 artwork link
    r.skip(MHIT_HEADER - 0x164)
    return t


def _parse_mhod_strings(body: bytes, count: int, track: Track) -> None:
    """Walk the mhods of one mhit; fill the string fields of @track."""
    r = Reader(body)
    for _ in range(count):
        chunk = r.pos  # chunk start (magic not yet consumed)
        r.magic(b"mhod", "mhod")
        hdr = r.u32()
        total = r.u32()
        mhod_type = r.u32()
        if hdr != MHOD_HEADER or total < hdr:
            raise FormatError("malformed mhod")
        payload = r.data[chunk + MHOD_HEADER : chunk + total]
        r.skip(total - 16)         # magic + 3 u32 already consumed
        field = _STRING_MHODS.get(mhod_type)
        if field is None:
            continue
        if mhod_type in _RAW_STRING_MHODS:
            value = payload.decode("utf-8", errors="replace") or None
        else:
            value = _parse_mhod_string(payload)
        if value:
            setattr(track, field, value)


def _parse_mhod_string(payload: bytes) -> str | None:
    """Decode a string mhod payload (starts at mhod + 24).

    Layout: string_type u32 (1/0 = UTF-16LE, 2 = UTF-8), byte length u32,
    8 bytes padding, then the string at +16.
    """
    if len(payload) < 16:
        return None
    s_type = int.from_bytes(payload[0:4], "little")
    length = int.from_bytes(payload[4:8], "little")
    raw = payload[16 : 16 + length]
    try:
        if s_type == 2:
            return raw.decode("utf-8")
        return raw.decode("utf-16-le")
    except UnicodeDecodeError:
        return None


def _parse_playlists(
    body: bytes, tracks_by_id: dict[int, Track], mhsd5: bool = False
) -> list[Playlist]:
    r = Reader(body)
    r.magic(b"mhlp", "playlist list")
    if r.u32() != MHLP_HEADER:
        raise FormatError("unexpected mhlp header size")
    count = r.u32()
    r.skip(MHLP_HEADER - 12)
    playlists: list[Playlist] = []
    for _ in range(count):
        chunk = r.pos  # chunk start (magic not yet consumed)  # mhyp start
        r.magic(b"mhyp", "playlist")
        hdr = r.u32()
        if hdr != MHYP_HEADER:
            raise FormatError(f"unexpected mhyp header size {hdr}")
        total = r.u32()
        mhod_count = r.u32()
        mhip_count = r.u32()
        if total < hdr or chunk + total > len(r.data):
            raise FormatError("mhyp overruns its section")
        pl = Playlist(
            name="",
            ptype=r.u8(),           # +0x14: 1 = master playlist
            flag1=r.u8(),
            flag2=r.u8(),
            flag3=r.u8(),
            timestamp=r.u32(),      # +0x18
            id=r.u64(),             # +0x1c
        )
        r.u32()                     # +0x24 unknown, always 0
        r.u16()                     # +0x28 string mhod count, always 1
        pl.podcastflag = r.u16()    # +0x2a
        pl.sortorder = r.u32()      # +0x2c
        if mhsd5:
            r.skip(32)              # +0x30
            pl.mhsd5_type = r.u16()  # +0x50
            r.u16()                  # +0x52 same value again
            r.u32()                  # +0x54 1 for rentals/ringtones, else 0
            r.skip(20)               # +0x58
        else:
            r.skip(34)              # +0x30
            r.u8()                  # +0x52 unknown
            pl.sortdescending = r.u8()  # +0x53
            r.skip(24)              # +0x54
        mhod_data = r.data[r.pos : chunk + total]
        r.skip(total - hdr)
        _parse_playlist_mhods(mhod_data, mhod_count, pl)
        _parse_playlist_mhips(mhod_data, mhod_count, mhip_count, pl, tracks_by_id)
        playlists.append(pl)
    return playlists


def _parse_playlist_mhods(body: bytes, count: int, pl: Playlist) -> None:
    """Walk a mhyp's mhods: the title, and SPL settings if smart."""
    r = Reader(body)
    for _ in range(count):
        chunk = r.pos  # chunk start (magic not yet consumed)
        r.magic(b"mhod", "mhod")
        hdr = r.u32()
        total = r.u32()
        mhod_type = r.u32()
        if hdr != MHOD_HEADER or total < hdr:
            raise FormatError("malformed mhod")
        payload = r.data[chunk + MHOD_HEADER : chunk + total]
        r.skip(total - 16)         # magic + 3 u32 already consumed
        if mhod_type == MHOD_TITLE:
            pl.name = _parse_mhod_string(payload) or pl.name
        elif mhod_type == MHOD_SPLPREF:
            pl.is_spl = True
            pl.splpref = _parse_splpref(payload)
        elif mhod_type == MHOD_SPLRULES:
            pl.is_spl = True
            pl.splrules = _parse_splrules(payload)
        # types 100 (preferences blob), 52, 53: regenerated at write.


def _parse_splpref(payload: bytes) -> SPLPref:
    if len(payload) < 16:
        raise FormatError("SPLPREF too short")
    return SPLPref(
        liveupdate=payload[0],
        checkrules=payload[1],
        checklimits=payload[2],
        limittype=payload[3],
        limitsort=payload[4],
        limitvalue=int.from_bytes(payload[8:12], "little"),
        matchcheckedonly=payload[12],
        limitsort_opposite=payload[13],
    )


def _parse_splrules(payload: bytes) -> SPLRules:
    """Smart playlist rules live in a big-endian 'SLst' block."""
    if len(payload) < 16 or payload[:4] != b"SLst":
        raise FormatError("SPLRULES without SLst block")
    n = int.from_bytes(payload[8:12], "big")
    rules = SPLRules(
        unk004=int.from_bytes(payload[4:8], "big"),
        match_operator=int.from_bytes(payload[12:16], "big"),
    )
    pos = 136  # SLst header: 4 + 3 u32 + 120 bytes padding
    for _ in range(n):
        if pos + 56 > len(payload):
            raise FormatError("SPLRULES overrun")
        rule = SPLRule(
            field=int.from_bytes(payload[pos : pos + 4], "big"),
            action=int.from_bytes(payload[pos + 4 : pos + 8], "big"),
        )
        length = int.from_bytes(payload[pos + 52 : pos + 56], "big")
        data = payload[pos + 56 : pos + 56 + length]
        if length == 0x44 and len(data) == 68:
            rule.fromvalue = int.from_bytes(data[0:8], "big")
            rule.fromdate = int.from_bytes(data[8:16], "big")
            rule.fromunits = int.from_bytes(data[16:24], "big")
            rule.tovalue = int.from_bytes(data[24:32], "big")
            rule.todate = int.from_bytes(data[32:40], "big")
            rule.tounits = int.from_bytes(data[40:48], "big")
            rule.unk052 = int.from_bytes(data[48:52], "big")
            rule.unk056 = int.from_bytes(data[52:56], "big")
            rule.unk060 = int.from_bytes(data[56:60], "big")
            rule.unk064 = int.from_bytes(data[60:64], "big")
            rule.unk068 = int.from_bytes(data[64:68], "big")
        elif length % 2 == 0:
            rule.string = data.decode("utf-16-be", errors="replace")
        else:
            raise FormatError(f"SPLRULES rule with odd length {length}")
        rules.rules.append(rule)
        pos += 56 + length
    return rules


def _parse_playlist_mhips(
    body: bytes,
    mhod_count: int,
    mhip_count: int,
    pl: Playlist,
    tracks_by_id: dict[int, Track],
) -> None:
    """Walk a mhyp's mhip entries; each references a track by id."""
    r = Reader(body)
    for _ in range(mhod_count):
        chunk = r.pos  # chunk start (magic not yet consumed)
        r.magic(b"mhod", "mhod")
        hdr = r.u32()
        total = r.u32()
        if hdr != MHOD_HEADER or total < hdr:
            raise FormatError("malformed mhod")
        r.skip(total - 12)         # magic + hdr + total already consumed
    for _ in range(mhip_count):
        chunk = r.pos  # chunk start (magic not yet consumed)
        r.magic(b"mhip", "playlist item")
        hdr = r.u32()
        total = r.u32()
        if hdr != MHP_HEADER or total < hdr or chunk + total > len(r.data):
            raise FormatError("malformed mhip")
        r.skip(8)   # childcount, podcastgroupflag
        r.u32()     # podcastgroupid
        track_id = r.u32()   # track id
        r.u32()     # timestamp
        r.u32()     # podcastgroupref
        r.skip(total - 36)
        track = tracks_by_id.get(track_id)
        if track is None:
            raise FormatError(
                f"playlist '{pl.name}' references unknown track id {track_id}"
            )
        pl.members.append(track)


def _parse_genius(body: bytes) -> str | None:
    raw = body
    while raw.endswith(b"\x00"):
        raw = raw[:-1]
    if not raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _merge_playlist_sections(mhsd_types: dict[int, list[Playlist]]) -> list[Playlist]:
    """Type 3 (podcast section) and type 2 (playlist section) carry the
    same playlists in every DB we have seen; dedupe by playlist id,
    preferring the type-3 copy (iTunes updates it last)."""
    merged: dict[int, Playlist] = {}
    for section in (3, 2):
        for pl in mhsd_types[section]:
            merged[pl.id] = pl
    # Master playlist must come first (device requirement).
    playlists = list(merged.values())
    mpl = next((p for p in playlists if p.is_mpl), None)
    if mpl is not None:
        playlists.remove(mpl)
        playlists.insert(0, mpl)
    return playlists
