"""Tolerant reader for the iPod's SysInfoExtended plist.

Apple's device plists are XML, but not always well-formed by the book:
this repo's nano 3G puts bare <key> elements directly inside <array>
(no <dict> wrapper), which makes plistlib raise. We only ever need the
top-level scalar keys (FireWireGUID, SerialNumber, FamilyID, DBVersion,
...), so a scanner that pairs every <key> with the next scalar value is
robust and simple. Nested structures are skipped by design.
"""

from __future__ import annotations

import re
from pathlib import Path

_KEY_RE = re.compile(r"<key>([^<]+)</key>")
_STRING_RE = re.compile(r"<string>(.*?)</string>", re.S)
_INTEGER_RE = re.compile(r"<integer>(-?\d+)</integer>")
_REAL_RE = re.compile(r"<real>([^<]+)</real>")
_DATE_RE = re.compile(r"<date>([^<]+)</date>")
_TRUE_RE = re.compile(r"<true\s*/>")
_FALSE_RE = re.compile(r"<false\s*/>")

_KEY_VALUE = re.compile(
    r"<key>(?P<key>[^<]+)</key>\s*"
    r"(?P<value>"
    r"<string>.*?</string>|"
    r"<integer>-?\d+</integer>|"
    r"<real>[^<]+</real>|"
    r"<date>[^<]+</date>|"
    r"<true\s*/>|<false\s*/>"
    r")",
    re.S,
)


def parse_sysinfo_extended(text: str) -> dict[str, str | int | float | bool]:
    """Extract every scalar key/value pair from a SysInfoExtended plist.

    The last occurrence of a key wins (Apple's own files repeat 'GUID'
    and 'Name' inside nested sections; top-level identity keys appear
    once).
    """
    out: dict[str, str | int | float | bool] = {}
    for match in _KEY_VALUE.finditer(text):
        key = match.group("key")
        raw = match.group("value")
        if raw.startswith("<string>"):
            value = raw[len("<string>") : -len("</string>")]
        elif raw.startswith("<integer>"):
            value = int(raw[len("<integer>") : -len("</integer>")])
        elif raw.startswith("<real>"):
            value = float(raw[len("<real>") : -len("</real>")])
        elif raw.startswith("<date>"):
            value = raw[len("<date>") : -len("</date>")]
        elif raw.startswith("<true"):
            value = True
        else:
            value = False
        out[key] = value
    return out

def read_sysinfo_extended(path: str | Path) -> dict[str, str | int | float | bool]:
    """Read and parse iPod_Control/Device/SysInfoExtended."""
    return parse_sysinfo_extended(Path(path).read_text(encoding="utf-8"))


def firewire_guid(info: dict[str, str | int | float | bool]) -> str | None:
    """The 16-hex-char FireWireGUID used as the hash58 key."""
    guid = info.get("FireWireGUID")
    if isinstance(guid, str) and len(guid) == 16:
        return guid
    return None
