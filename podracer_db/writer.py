"""iTunesDB writer: Library -> bytes.

Emits a complete fresh DB from library state (rebuild-from-state):
track/playlist ids are renumbered, the sort indexes (mhod 52/53) and the
album/artist sections are regenerated, and the header checksum (hash58)
is recomputed when the device FireWire GUID is known.

Section order matches iTunes/libgpod output: mhsd 1 (tracks), 3
(podcast playlists), 2 (playlists), 4 (albums), 8 (artists), 6 and 10
(empty), 5 (smart playlists), and 9 (genius) when a cuid exists.
"""

from __future__ import annotations

import random

from .binary import Writer
from .hash58 import apply_hash58
from .model import FIRST_IPOD_ID, Library, Playlist, SPLRule, SPLRules, Track
from .parser import (
    MHOD_ALBUM,
    MHOD_ALBUMARTIST,
    MHOD_ALBUM_ALBUM,
    MHOD_ALBUM_ARTIST,
    MHOD_ALBUM_ARTIST_MHII,
    MHOD_ALBUM_SORT_ARTIST,
    MHOD_ARTIST,
    MHOD_CATEGORY,
    MHOD_COMMENT,
    MHOD_COMPOSER,
    MHOD_DESCRIPTION,
    MHOD_FILETYPE,
    MHOD_GENRE,
    MHOD_GROUPING,
    MHOD_KEYWORDS,
    MHOD_LIBPLAYLISTINDEX,
    MHOD_LIBPLAYLISTJUMPTABLE,
    MHOD_PATH,
    MHOD_PLAYLIST,
    MHOD_PODCASTRSS,
    MHOD_PODCASTURL,
    MHOD_SORT_ALBUM,
    MHOD_SORT_ALBUMARTIST,
    MHOD_SORT_ARTIST,
    MHOD_SORT_COMPOSER,
    MHOD_SORT_TITLE,
    MHOD_SORT_TVSHOW,
    MHOD_SPLPREF,
    MHOD_SPLRULES,
    MHOD_SUBTITLE,
    MHOD_TITLE,
    MHOD_TVEPISODE,
    MHOD_TVNETWORK,
    MHOD_TVSHOW,
    MHBD_HEADER,
    MHLP_HEADER,
    MHLT_HEADER,
    MHOD_HEADER,
    MHP_HEADER,
    MHYP_HEADER,
    MHIT_HEADER,
    MHSD_HEADER,
)

# mhsd5 section types (the device's main-menu sections); rentals and
# ringtones carry a "1" marker byte at mhyp+0x54.
MHSD5_MOVIES = 2
MHSD5_TV_SHOWS = 3
MHSD5_MUSIC = 4
MHSD5_AUDIOBOOKS = 5
MHSD5_RINGTONES = 6
MHSD5_MOVIE_RENTALS = 7

# Sort orders of the library index mhods (mhod 52/53), in the order
# libgpod writes them inside the master playlist.
SORT_TITLE = 0x03
SORT_ALBUM = 0x04
SORT_ARTIST = 0x05
SORT_GENRE = 0x07
SORT_COMPOSER = 0x12

# Podcast playlists carry this flag (mhyp+0x2a).
PODCAST_FLAG = 2


def write_db(lib: Library, firewire_guid: str | None = None) -> bytes:
    """Serialize @lib to iTunesDB bytes.

    @firewire_guid: 16-hex-char FireWireGUID from the device's
    SysInfoExtended plist; enables the hash58 header checksum the nano
    3G and classic expect. Without it the scheme field stays 0.
    """
    prep = _prepare(lib)
    w = Writer()

    children = 8 + (1 if lib.genius_cuid else 0)
    mhbd_seek = w.pos
    _mk_mhbd(w, lib, children)
    _mk_mhsd_tracks(w, lib, prep)
    _mk_mhsd_playlists(w, lib, mhsd_type=3)
    _mk_mhsd_playlists(w, lib, mhsd_type=2)
    _mk_mhsd_albums(w, prep)
    _mk_mhsd_artists(w, prep)
    _mk_mhsd_empty(w, sec_type=6)
    _mk_mhsd_empty(w, sec_type=10)
    _mk_mhsd_playlists(w, lib, mhsd_type=5)
    if lib.genius_cuid:
        _mk_mhsd_genius(w, lib.genius_cuid)

    w.patch_u32(mhbd_seek + 8, w.pos)  # mhbd total size
    out = w.finish()
    if firewire_guid:
        out = apply_hash58(out, firewire_guid)
    return out


# ---------------------------------------------------------------------------
# prepare: renumber ids, order tracks by the master playlist, assign
# album/artist ids.

class _Prep:
    def __init__(self) -> None:
        self.track_ids: dict[Track, int] = {}
        self.albums: list[tuple[tuple, Track]] = []    # (key, exemplar)
        self.artists: list[tuple[str, Track]] = []


def _prepare(lib: Library) -> _Prep:
    mpl = lib.master_playlist()
    if mpl is None:
        raise ValueError("library has no master playlist")

    # Tracks are written in MPL order (mhip positions and the mhod52
    # indexes reference the track-list positions).
    ordered = list(mpl.members)
    in_mpl = {id(t) for t in ordered}
    ordered += [t for t in lib.tracks if id(t) not in in_mpl]

    prep = _Prep()
    next_id = FIRST_IPOD_ID
    album_ids: dict[tuple, int] = {}
    artist_ids: dict[str, int] = {}
    composer_ids: dict[str, int] = {}
    for track in ordered:
        track.id = next_id
        next_id += 1
        prep.track_ids[track] = track.id

        album_key = (track.tvshow, track.album, track.albumartist or track.artist)
        if album_key[1]:
            aid = album_ids.get(album_key)
            if aid is None:
                aid = len(album_ids) + 1
                album_ids[album_key] = aid
                prep.albums.append((album_key, track))
            track.album_id = aid
        if track.artist:
            aid = artist_ids.get(track.artist)
            if aid is None:
                aid = len(artist_ids) + 1
                artist_ids[track.artist] = aid
                prep.artists.append((track.artist, track))
            track.artist_id = aid
        if track.composer:
            aid = composer_ids.get(track.composer)
            if aid is None:
                aid = len(composer_ids) + 1
                composer_ids[track.composer] = aid
            track.composer_id = aid
    return prep


# ---------------------------------------------------------------------------
# header + section writers. Every chunk is: magic, header length, total
# length (patched after the body), then type-specific fields.

def _mk_mhbd(w: Writer, lib: Library, children: int) -> None:
    w.magic("mhbd")
    w.u32(MHBD_HEADER)
    w.u32(0)                       # total size, patched by caller
    w.u32(lib.compressed)
    w.u32(lib.version)
    w.u32(children)
    w.u64(lib.db_id)
    w.u16(lib.platform)
    w.u16(lib.unk_0x22)
    w.u64(lib.id_0x24)
    w.u32(0)                       # unk_0x2c
    w.u16(0)                       # hashing scheme: stays 0 (nano 3G requires it)
    w.zeros(20)                    # unk_0x32
    w.u16(lib.lang)
    w.u64(lib.pid)
    w.u32(lib.unk_0x50)
    w.u32(lib.unk_0x54)
    w.zeros(20)                    # hash58 slot
    w.u32(lib.tzoffset)
    w.u16(0)                       # checksum type selector (hash58)
    w.zeros(46)                    # hash72 slot
    w.u16(lib.audio_language)
    w.u16(lib.subtitle_language)
    w.u16(lib.unk_0xa4)
    w.u16(lib.unk_0xa6)
    w.u16(lib.unk_0xa8)
    w.u8(0)                        # align
    w.zeros(57)                    # hashAB slot
    w.zeros(16)                    # padding
    assert w.pos == 244


def _mk_mhsd(w: Writer, sec_type: int) -> int:
    w.magic("mhsd")
    w.u32(MHSD_HEADER)
    w.u32(0)                       # total, patched by caller
    w.u32(sec_type)
    w.zeros(80)
    return w.pos - 96               # section start (for the total patch)


def _mk_mhlt(w: Writer, count: int) -> None:
    w.magic("mhlt")
    w.u32(MHLT_HEADER)
    w.u32(count)
    w.zeros(80)


def _mk_mhsd_tracks(w: Writer, lib: Library, prep: _Prep) -> None:
    start = _mk_mhsd(w, 1)
    _mk_mhlt(w, len(prep.track_ids))
    for track, _tid in sorted(prep.track_ids.items(), key=lambda kv: kv[1]):
        chunk = w.pos
        _mk_mhit_fixed(w, track, lib.id_0x24)
        mhod_count = 0
        for mhod_type, value in _track_mhods(track):
            _mk_mhod_string(w, mhod_type, value)
            mhod_count += 1
        w.patch_u32(chunk + 8, w.pos - chunk)      # mhit total
        w.patch_u32(chunk + 12, mhod_count)
    w.patch_u32(start + 8, w.pos - start)          # mhsd total


def _mk_mhit_fixed(w: Writer, t: Track, lib_id_0x24: int) -> None:
    start = w.pos
    w.magic("mhit")
    w.u32(MHIT_HEADER)
    w.u32(0)                       # total, patched
    w.u32(0)                       # mhod count, patched
    w.u32(t.id)
    w.u32(t.visible)
    w.raw(t.filetype_marker.to_bytes(4, "little"))
    w.u8(t.type1)
    w.u8(t.type2)
    w.u8(t.compilation)
    w.u8(t.rating)
    w.u32(t.time_modified)
    w.u32(t.size)
    w.u32(t.tracklen)
    w.u32(t.track_nr)
    w.u32(t.tracks)
    w.u32(t.year)
    w.u32(t.bitrate)
    w.u32(((t.samplerate & 0xFFFF) << 16) | (t.samplerate_low & 0xFFFF))
    w.u32(t.volume)
    w.u32(t.starttime)
    w.u32(t.stoptime)
    w.u32(t.soundcheck)
    w.u32(t.playcount)
    w.u32(t.playcount2)
    w.u32(t.time_played)
    w.u32(t.cd_nr)
    w.u32(t.cds)
    w.u32(t.drm_userid)
    w.u32(t.time_added)
    w.u32(t.bookmark_time)
    w.u64(t.dbid)
    w.u8(t.checked)
    w.u8(t.app_rating)
    w.u16(t.bpm)
    w.u16(t.artwork_count)
    w.u16(t.unk126)
    w.u32(t.artwork_size)
    w.u32(t.unk132)
    w.f32(t.samplerate2)
    w.u32(t.time_released)
    w.u16(t.unk144)
    w.u16(t.explicit_flag)
    w.u32(t.unk148)
    w.u32(t.unk152)
    w.u32(t.skipcount)
    w.u32(t.last_skipped)
    w.u8(t.has_artwork)
    w.u8(t.skip_when_shuffling)
    w.u8(t.remember_playback_position)
    w.u8(t.flag4)
    w.u64(t.dbid2)
    w.u8(t.lyrics_flag)
    w.u8(t.movie_flag)
    w.u8(t.mark_unplayed)
    w.u8(t.unk179)
    w.u32(t.unk180)
    w.u32(t.pregap)
    w.u64(t.samplecount)
    w.u32(t.unk196)
    w.u32(t.postgap)
    w.u32(t.unk204)
    w.u32(t.mediatype)
    w.u32(t.season_nr)
    w.u32(t.episode_nr)
    w.u32(t.unk220)
    w.u32(t.unk224)
    w.u32(t.unk228)
    w.u32(t.unk232)
    w.u32(t.unk236)
    w.u32(t.unk240)
    w.u32(t.unk244)
    w.u32(t.gapless_data)
    w.u32(t.unk252)
    w.u16(t.gapless_track_flag)
    w.u16(t.gapless_album_flag)
    w.zeros(0x120 - 0x104)         # to the album_id slot
    w.u32(t.album_id)              # +0x120
    w.u64(lib_id_0x24)             # +0x124 echoes mhbd+0x24
    w.u32(t.size)                  # +0x12c filesize again
    w.u32(0)
    w.u64(0x808080808080)
    w.u32(0)
    w.zeros(8)
    w.u32(0)                       # book flags
    w.zeros(20)
    w.u32(t.mhii_link)             # +0x160
    w.u32(0)
    w.u32(1)
    w.u32(0)
    w.zeros(112)
    w.u32(t.artist_id)             # +0x1e0
    w.zeros(16)
    w.u32(t.composer_id)           # +0x1f4
    w.zeros(80)
    assert w.pos - start == MHIT_HEADER, w.pos - start


def _track_mhods(t: Track) -> list[tuple[int, str]]:
    """The string mhods for one track, in the order iTunes writes them."""
    out: list[tuple[int, str]] = []
    for mhod_type, field in (
        (MHOD_TITLE, "title"),
        (MHOD_ARTIST, "artist"),
        (MHOD_ALBUM, "album"),
        (MHOD_FILETYPE, "filetype"),
        (MHOD_COMMENT, "comment"),
        (MHOD_PATH, "ipod_path"),
        (MHOD_GENRE, "genre"),
        (MHOD_CATEGORY, "category"),
        (MHOD_COMPOSER, "composer"),
        (MHOD_GROUPING, "grouping"),
        (MHOD_DESCRIPTION, "description"),
        (MHOD_SUBTITLE, "subtitle"),
        (MHOD_TVSHOW, "tvshow"),
        (MHOD_TVEPISODE, "tvepisode"),
        (MHOD_TVNETWORK, "tvnetwork"),
        (MHOD_ALBUMARTIST, "albumartist"),
        (MHOD_KEYWORDS, "keywords"),
        (MHOD_PODCASTURL, "podcasturl"),
        (MHOD_PODCASTRSS, "podcastrss"),
        (MHOD_SORT_ARTIST, "sort_artist"),
        (MHOD_SORT_TITLE, "sort_title"),
        (MHOD_SORT_ALBUM, "sort_album"),
        (MHOD_SORT_ALBUMARTIST, "sort_albumartist"),
        (MHOD_SORT_COMPOSER, "sort_composer"),
        (MHOD_SORT_TVSHOW, "sort_tvshow"),
    ):
        value = getattr(t, field)
        if value:
            out.append((mhod_type, value))
    return out


def _mk_mhod_string(w: Writer, mhod_type: int, value: str) -> None:
    """A string mhod: 24-byte header, 16-byte prefix, UTF-16LE payload."""
    payload = value.encode("utf-16-le")
    w.magic("mhod")
    w.u32(MHOD_HEADER)
    w.u32(40 + len(payload))
    w.u32(mhod_type)
    w.zeros(8)
    w.u32(1)                       # string type: UTF-16LE
    w.u32(len(payload))
    w.u32(1)
    w.u32(0)
    w.raw(payload)


def _mk_mhsd_playlists(w: Writer, lib: Library, mhsd_type: int) -> None:
    start = _mk_mhsd(w, mhsd_type)
    playlists = lib.playlists if mhsd_type != 5 else lib.mhsd5_playlists
    w.magic("mhlp")
    w.u32(MHLP_HEADER)
    w.u32(0)                       # count, patched below
    w.zeros(80)
    for pl in playlists:
        _mk_mhyp(w, pl, mhsd_type)
    w.patch_u32(start + MHSD_HEADER + 8, len(playlists))
    w.patch_u32(start + 8, w.pos - start)


def _mk_mhyp(w: Writer, pl: Playlist, mhsd_type: int) -> None:
    chunk = w.pos
    is_mpl = pl.is_mpl
    if is_mpl and pl.members:
        mhod_count = 12            # title + prefs + 5 sort pairs
    elif pl.is_spl:
        mhod_count = 4             # title + prefs + SPLPREF + SPLRULES
    else:
        mhod_count = 2             # title + prefs
    w.magic("mhyp")
    w.u32(MHYP_HEADER)
    w.u32(0)                       # total, patched
    w.u32(mhod_count)
    w.u32(0)                       # mhip count, patched
    w.u8(pl.ptype)
    w.u8(pl.flag1)
    w.u8(pl.flag2)
    w.u8(pl.flag3)
    w.u32(pl.timestamp)
    w.u64(pl.id)
    w.u32(0)
    w.u16(1)                       # string mhod count
    w.u16(pl.podcastflag)
    w.u32(pl.sortorder)
    if mhsd_type == 5:
        w.zeros(32)
        w.u16(pl.mhsd5_type)
        w.u16(pl.mhsd5_type)
        w.u32(1 if pl.mhsd5_type in (MHSD5_MOVIE_RENTALS, MHSD5_RINGTONES) else 0)
        w.zeros(20)
    else:
        w.zeros(34)
        w.u8(0)
        w.u8(pl.sortdescending)
        w.zeros(24)
    assert w.pos - chunk == MHYP_HEADER

    _mk_mhod_string(w, MHOD_TITLE, pl.name)
    _mk_long_mhod_playlist(w)
    if is_mpl and pl.members:
        for sorttype, field in (
            (SORT_TITLE, "title"),
            (SORT_ARTIST, "artist"),
            (SORT_ALBUM, "album"),
            (SORT_GENRE, "genre"),
            (SORT_COMPOSER, "composer"),
        ):
            entries = _sort_entries(pl, field)
            _mk_mhod52(w, sorttype, entries)
            _mk_mhod53(w, sorttype, entries)
    elif pl.is_spl:
        _mk_mhod_splpref(w, pl)
        _mk_mhod_splrules(w, pl)

    if mhsd_type == 5:
        w.patch_u32(chunk + 16, 0)  # no mhips in smart-playlist sections
    elif pl.podcastflag == PODCAST_FLAG and mhsd_type == 3:
        mhip_count = _mk_podcast_mhips(w, pl)
        w.patch_u32(chunk + 16, mhip_count)
    else:
        for pos, track in enumerate(pl.members):
            mhip_seek = w.pos
            _mk_mhip(w, 1, 0, 0, track.id, 0)
            _mk_mhod_playlist_pos(w, pos)
            # The mhod counts as a child: the mhip total covers both.
            w.patch_u32(mhip_seek + 8, w.pos - mhip_seek)
        w.patch_u32(chunk + 16, len(pl.members))
    w.patch_u32(chunk + 8, w.pos - chunk)


def _sort_entries(pl: Playlist, field: str) -> list[tuple[int, int, str]]:
    """Sorted (track_index, jump_letter, sort_text) for one sort order.

    Indexes reference positions in the track list, which the writer
    orders by the master playlist. 'The X' artists sort as 'X, The'.
    Python's codepoint order matches UTF-8 byte order (what glib's
    C-locale collation does); the device needs a consistent order that
    matches its jump-table letters.
    """
    index = {id(t): i for i, t in enumerate(pl.members)}
    entries = []
    for t in pl.members:
        if field == "artist" and t.sort_artist:
            text = t.sort_artist
        elif field == "album" and t.sort_album:
            text = t.sort_album
        else:
            text = getattr(t, field) or ""
        if field == "artist" and text[:4].lower() == "the ":
            text = text[4:] + ", The\x01\x01\x01\x01\x01"
        entries.append((index[id(t)], text))
    entries.sort(key=lambda e: e[1])
    return [(idx, _jump_letter(text), text) for idx, text in entries]


def _jump_letter(text: str) -> int:
    """First alphanumeric character, uppercased; digits and everything
    else map to '0' (the device's jump-table convention)."""
    for ch in text:
        if ch.isalnum():
            if ch.isalpha():
                return ord(ch.upper())
            return ord("0")
    return ord("0")


def _mk_mhod52(w: Writer, sorttype: int, entries: list[tuple[int, int, str]]) -> None:
    """Library sort index: sorted track positions (mhod 52)."""
    w.magic("mhod")
    w.u32(MHOD_HEADER)
    w.u32(72 + 4 * len(entries))
    w.u32(MHOD_LIBPLAYLISTINDEX)
    w.zeros(8)
    w.u32(sorttype)
    w.u32(len(entries))
    w.zeros(40)
    for index, _letter, _text in entries:
        w.u32(index)


def _mk_mhod53(w: Writer, sorttype: int, entries: list[tuple[int, int, str]]) -> None:
    """Jump table for one sort order: letter -> run of positions."""
    runs: list[tuple[int, int, int]] = []  # (letter, start, count)
    for i, (_index, letter, _text) in enumerate(entries):
        if runs and runs[-1][0] == letter:
            runs[-1] = (letter, runs[-1][1], runs[-1][2] + 1)
        else:
            runs.append((letter, i, 1))
    w.magic("mhod")
    w.u32(MHOD_HEADER)
    w.u32(40 + 12 * len(runs))
    w.u32(MHOD_LIBPLAYLISTJUMPTABLE)
    w.zeros(8)
    w.u32(sorttype)
    w.u32(len(runs))
    w.zeros(8)
    for letter, start, count in runs:
        w.u16(letter)
        w.u16(0)
        w.u32(start)
        w.u32(count)


def _mk_mhod_splpref(w: Writer, pl: Playlist) -> None:
    pref = pl.splpref
    w.magic("mhod")
    w.u32(MHOD_HEADER)
    w.u32(96)
    w.u32(MHOD_SPLPREF)
    w.zeros(8)
    w.u8(pref.liveupdate)
    w.u8(pref.checkrules)
    w.u8(pref.checklimits)
    w.u8(pref.limittype)
    w.u8(pref.limitsort & 0xFF)
    w.u8(0)
    w.u8(0)
    w.u8(0)
    w.u32(pref.limitvalue)
    w.u8(pref.matchcheckedonly)
    w.u8(pref.limitsort_opposite)
    w.u8(0)
    w.u8(0)
    w.zeros(56)

def _mk_mhod_splrules(w: Writer, pl: Playlist) -> None:
    rules = pl.splrules if pl.splrules else SPLRules()
    body = Writer()
    body.magic("SLst")
    body.be_u32(rules.unk004)
    body.be_u32(len(rules.rules))
    body.be_u32(rules.match_operator)
    body.zeros(120)
    for rule in rules.rules:
        _mk_splrule(body, rule)
    w.magic("mhod")
    w.u32(MHOD_HEADER)
    w.u32(MHOD_HEADER + body.pos)
    w.u32(MHOD_SPLRULES)
    w.zeros(8)
    w.raw(body.finish())


def _mk_splrule(w: Writer, rule: SPLRule) -> None:
    w.be_u32(rule.field)
    w.be_u32(rule.action)
    w.zeros(44)
    if rule.string is not None:
        raw = rule.string.encode("utf-16-be")
        w.be_u32(len(raw))
        w.raw(raw)
    else:
        w.be_u32(0x44)
        w.be_u64(rule.fromvalue)
        w.be_u64(rule.fromdate)
        w.be_u64(rule.fromunits)
        w.be_u64(rule.tovalue)
        w.be_u64(rule.todate)
        w.be_u64(rule.tounits)
        w.be_u32(rule.unk052)
        w.be_u32(rule.unk056)
        w.be_u32(rule.unk060)
        w.be_u32(rule.unk064)
        w.be_u32(rule.unk068)



def _mk_mhip(w: Writer, childcount: int, groupflag: int, groupid: int,
             trackid: int, groupref: int) -> None:
    w.magic("mhip")
    w.u32(MHP_HEADER)
    w.u32(0)                       # total, patched by caller
    w.u32(childcount)
    w.u32(groupflag)
    w.u32(groupid)
    w.u32(trackid)
    w.u32(0)                       # timestamp
    w.u32(groupref)
    w.zeros(40)


def _mk_mhod_playlist_pos(w: Writer, pos: int) -> None:
    w.magic("mhod")
    w.u32(MHOD_HEADER)
    w.u32(44)
    w.u32(MHOD_PLAYLIST)
    w.zeros(8)
    w.u32(pos)
    w.zeros(16)


def _mk_podcast_mhips(w: Writer, pl: Playlist) -> int:
    """Podcast feeds are grouped by album with synthetic mhips."""
    groups: dict[str, list[Track]] = {}
    for track in pl.members:
        groups.setdefault(track.album or "", []).append(track)
    mhip_count = 0
    next_id = 1000
    for album, members in groups.items():
        gid = next_id
        next_id += 1
        mhip_seek = w.pos
        _mk_mhip(w, 1, 256, gid, 0, 0)
        _mk_mhod_string(w, MHOD_TITLE, album)
        w.patch_u32(mhip_seek + 8, w.pos - mhip_seek)
        mhip_count += 1
        for track in members:
            mhip_seek = w.pos
            _mk_mhip(w, 1, 0, next_id, track.id, gid)
            _mk_mhod_playlist_pos(w, next_id)
            next_id += 1
            w.patch_u32(mhip_seek + 8, w.pos - mhip_seek)
            mhip_count += 1
    return mhip_count


def _mk_long_mhod_playlist(w: Writer) -> None:
    """The preferences mhod every playlist carries (iTunes column
    prefs). Total 648 bytes, verified against a device-written DB;
    the values are identical on every real DB."""
    w.magic("mhod")
    w.u32(MHOD_HEADER)
    w.u32(648)
    w.u32(MHOD_PLAYLIST)
    w.zeros(8)
    w.zeros(16)
    for v in (0x010084, 0x05, 0x09, 0x03, 0x120001):
        w.u32(v)
    w.zeros(12)
    for v in (0xC80002, 0x3C000D, 0x7D0004, 0x7D0003, 0x640008):
        w.u32(v)
        w.zeros(12)
    w.u32(0x640017)
    w.u32(0x01)
    w.zeros(8)
    w.u32(0x500014)
    w.u32(0x01)
    w.zeros(8)
    w.u32(0x7D0015)
    w.u32(0x01)
    w.zeros(8)
    w.zeros(448)


def _mk_mhsd_albums(w: Writer, prep: _Prep) -> None:
    start = _mk_mhsd(w, 4)
    w.magic("mhla")
    w.u32(MHLP_HEADER)
    w.u32(len(prep.albums))
    w.zeros(80)
    for (_tvshow, album, artist), track in prep.albums:
        chunk = w.pos
        w.magic("mhia")
        w.u32(88)
        w.u32(0)                   # total, patched
        w.u32(0)                   # mhod count, patched
        w.u32(track.album_id)
        w.u64(random.getrandbits(64))  # sqlite id, unused on v1 devices
        w.u32(2)
        w.zeros(56)
        _mk_mhod_string(w, MHOD_ALBUM_ALBUM, album)
        mhod_count = 1
        if artist:
            _mk_mhod_string(w, MHOD_ALBUM_ARTIST, artist)
            mhod_count += 1
        if track.sort_albumartist or track.sort_artist:
            _mk_mhod_string(
                w, MHOD_ALBUM_SORT_ARTIST, track.sort_albumartist or track.sort_artist
            )
            mhod_count += 1
        w.patch_u32(chunk + 8, w.pos - chunk)
        w.patch_u32(chunk + 12, mhod_count)
    w.patch_u32(start + 8, w.pos - start)


def _mk_mhsd_artists(w: Writer, prep: _Prep) -> None:
    start = _mk_mhsd(w, 8)
    w.magic("mhli")
    w.u32(MHLP_HEADER)
    w.u32(len(prep.artists))
    w.zeros(80)
    for artist, track in prep.artists:
        chunk = w.pos
        w.magic("mhii")
        w.u32(80)
        w.u32(0)                   # total, patched
        w.u32(0)                   # mhod count, patched
        w.u32(track.artist_id)
        w.u64(random.getrandbits(64))
        w.u32(2)
        w.zeros(48)
        _mk_mhod_string(w, MHOD_ALBUM_ARTIST_MHII, artist)
        w.patch_u32(chunk + 8, w.pos - chunk)
        w.patch_u32(chunk + 12, 1)
    w.patch_u32(start + 8, w.pos - start)


def _mk_mhsd_empty(w: Writer, sec_type: int) -> None:
    start = _mk_mhsd(w, sec_type)
    _mk_mhlt(w, 0)
    w.patch_u32(start + 8, w.pos - start)


def _mk_mhsd_genius(w: Writer, cuid: str) -> None:
    start = _mk_mhsd(w, 9)
    w.raw(cuid.encode("utf-8"))
    w.patch_u32(start + 8, w.pos - start)
