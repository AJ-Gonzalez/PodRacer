"""macOS transport: the diskutil CLI parsed with plistlib.

The darwin backend behind the same five-method Transport protocol
(see device.py); no D-Bus daemon, no pyobjc, no new dependencies —
diskutil is part of every macOS install. It reads MediaType 'iPod'
for Apple media (diskarbitrationd identifies the device from IOKit),
which is what device.py's Apple-vendor filter keys on here — the
USB-vendor sniffing udisks2 offers on Linux is not needed.

Subprocess calls cost 30-130 ms and the app polls the device layer
every 3 s, so vendor classification is memoized per (DeviceIdentifier,
VolumeUUID) — keying on the UUID too, not just the disk number,
because macOS reuses diskN identifiers for whoever plugs in next.
`diskutil list -plist` is then the only per-tick cost.

Thin adapter on purpose: all interpretation (Apple-vendor filter,
mountpoint matching) lives in device.py so tests can fake the
transport without subprocesses.
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

from .device import APPLE_VENDOR, DeviceError, Partition

DISKUTIL = "/usr/sbin/diskutil"
# A hung diskutil must never wedge the GUI poll tick.
TIMEOUT = 10


def _run(*args: str) -> bytes:
    """One diskutil invocation; stdout as bytes, errors as DeviceError."""
    try:
        proc = subprocess.run(
            [DISKUTIL, *args], capture_output=True, timeout=TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DeviceError(f"{args[0]} timed out: {exc}") from None
    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip() or b"unknown error"
        raise DeviceError(f"{args[0]} failed: {err.decode(errors='replace')}")
    return proc.stdout


def disk_info(ident: str) -> dict:
    """diskutil info -plist <device-or-mountpoint>, as a plain dict."""
    return plistlib.loads(_run("info", "-plist", ident))


def device_for_mountpoint(mountpoint: Path) -> str | None:
    """BSD device (e.g. disk8s1) mounted at @mountpoint, per diskutil.

    Ground truth for eject/rename: keyed by the live mountpoint, so a
    renamed volume cannot leave the caller pointing at a stale name.
    """
    ident = disk_info(str(mountpoint)).get("DeviceIdentifier")
    return ident if isinstance(ident, str) else None


def mountpoint_for(ident: str) -> Path | None:
    """Current mountpoint of @ident, or None when it is not mounted."""
    mp = disk_info(ident).get("MountPoint")
    return Path(mp) if isinstance(mp, str) and mp else None


def _classify(ident: str) -> str:
    """Vendor string for @ident: 'apple' exactly when diskutil says so."""
    if str(disk_info(ident).get("MediaType", "")).lower() == "ipod":
        return APPLE_VENDOR
    return ""


class DiskUtil:
    """diskutil-backed transport: partition listing, mount, unmount, rename."""

    def __init__(self) -> None:
        self._vendors: dict[tuple[str, str], str] = {}

    def partitions(self) -> list[Partition]:
        out: list[Partition] = []
        seen: set[str] = set()
        for entry in plistlib.loads(_run("list", "-plist")).get(
                "AllDisksAndPartitions", []):
            # Partitions covers every partition table; Volumes covers
            # superfloppy media (FAT with no partition table — shuffles).
            for part in entry.get("Partitions", []) + entry.get("Volumes", []):
                if str(part.get("Content", "")) == "EFI":
                    continue  # EFI system partitions are never iPods
                if not part.get("VolumeName"):
                    continue  # no filesystem to carry a name to match on
                ident = str(part.get("DeviceIdentifier", ""))
                if not ident:
                    continue
                seen.add(ident)
                key = (ident, str(part.get("VolumeUUID", "")))
                vendor = self._vendors.get(key)
                if vendor is None:
                    vendor = _classify(ident)
                    self._vendors[key] = vendor
                if vendor == APPLE_VENDOR:
                    out.append(Partition(
                        device=ident,
                        label=str(part.get("VolumeName", "")),
                        vendor=vendor,
                    ))
        # Forget media that left the system so a reused diskN cannot
        # inherit the previous device's verdict.
        self._vendors = {
            key: verdict for key, verdict in self._vendors.items()
            if key[0] in seen
        }
        return out

    def mount(self, device: str) -> str:
        """Mount @device, returning its mountpoint (idempotent).

        diskutil errors on an already-mounted volume; a volume macOS
        mounted between our scan and this call must read as success.
        """
        info = disk_info(device)
        if not info.get("MountPoint"):
            try:
                _run("mount", device)
            except DeviceError:
                # A slow mount can outlive the subprocess timeout and
                # still land (diskarbitrationd completes on its own).
                if not disk_info(device).get("MountPoint"):
                    raise
            info = disk_info(device)
        return str(info.get("MountPoint") or "")

    def unmount(self, device: str) -> None:
        """Unmount the volume (idempotent: already unmounted = done).

        The re-check mirrors mount(): a first unmount on a freshly
        plugged volume (Spotlight/fseventsd writers active) can
        outlive the subprocess timeout while the unmount lands.
        """
        if not disk_info(device).get("MountPoint"):
            return
        try:
            _run("unmount", device)
        except DeviceError:
            if disk_info(device).get("MountPoint"):
                raise

    def set_label(self, device: str, label: str) -> None:
        """Rename the filesystem volume label (FAT label for the iPod).

        diskutil renames the live volume: on a mounted volume macOS
        moves the mountpoint to /Volumes/<label> immediately, which
        device.rename_label mirrors back onto the IPod.
        """
        if str(disk_info(device).get("VolumeName", "")) == label:
            return
        _run("rename", device, label)

    def reachable(self) -> bool:
        return Path(DISKUTIL).exists()
