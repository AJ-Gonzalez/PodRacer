"""iPod detection, mounting, and device identity.

Everything here talks to the udisks2 daemon over D-Bus (see udisks2.py
for the transport). No udisksctl/lsblk subprocesses: direct D-Bus is
init-agnostic, distro-agnostic, and works inside a Flatpak sandbox with
the system bus exposed. The app polls `current_ipod()` from a timer;
there is no event source to subscribe to without udev, and polling
every few seconds is plenty for a device you plug in by hand.

The logic here stays testable without a display: the D-Bus transport is
injected (Transport protocol), so tests use a fake and never touch
QtDBus. All interpretation (Apple vendor filter, mountpoint matching)
lives in this module, not in the transport.

Device identity comes from `iPod_Control/Device/SysInfoExtended` (see
sysinfo.py): the FireWireGUID there is the hash58 key, and the serial
numbers the model (nano 3G = 05ac:1262; libgpod maps serials to
models). The volume label is only the mount-point name, NOT the device
name the iPod shows; that lives in the master playlist title.
"""

from __future__ import annotations

import os
import pwd
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import sysinfo
from .udisks2 import DeviceError, Partition, UDisks2

APPLE_VENDOR = "apple"


class Transport(Protocol):
    """The udisks2 access device.py needs; implemented by udisks2.UDisks2,
    faked in tests. Keeps all interpretation logic in the Qt-free layer."""

    def partitions(self) -> list[Partition]: ...

    def block_device_for(self, mountpoint: Path) -> str | None: ...

    def mount(self, device: str) -> str: ...

    def unmount(self, device: str) -> None: ...

    def reachable(self) -> bool: ...


_transport: Transport | None = None


def _get_transport() -> Transport:
    global _transport
    if _transport is None:
        _transport = UDisks2()
    return _transport


@dataclass
class IPod:
    """One mounted iPod: filesystem location plus identity."""

    mountpoint: Path
    label: str | None = None
    block_device: str | None = None
    guid: str | None = None
    serial: str | None = None
    family_id: int | None = None
    db_version: int | None = None
    sysinfo: dict[str, Any] = field(default_factory=dict)

    @property
    def ipod_control(self) -> Path:
        return self.mountpoint / "iPod_Control"

    @property
    def db_path(self) -> Path:
        return self.ipod_control / "iTunes" / "iTunesDB"


def _media_root() -> Path:
    return Path("/run/media") / pwd.getpwuid(os.getuid()).pw_name


def mounted_ipods(media_root: Path | None = None) -> list[IPod]:
    """All mounted iPods under /run/media/<user> (or @media_root)."""
    root = media_root or _media_root()
    if not root.is_dir():
        return []
    found: list[IPod] = []
    for candidate in sorted(root.iterdir()):
        if (candidate / "iPod_Control").is_dir():
            found.append(IPod(mountpoint=candidate, label=candidate.name))
    return found


def _apple_partitions() -> list[tuple[str, str]]:
    """(device, label) for every partition of an Apple drive."""
    return [
        (p.device, p.label)
        for p in _get_transport().partitions()
        if p.vendor.strip().lower() == APPLE_VENDOR
    ]


def _block_device_for(mountpoint: Path) -> str | None:
    return _get_transport().block_device_for(mountpoint)


def _fill_identity(ipod: IPod) -> None:
    """Attach sysinfo identity (GUID, serial, family id) from the device."""
    if ipod.serial is not None:
        return
    sysinfo_path = ipod.ipod_control / "Device" / "SysInfoExtended"
    if not sysinfo_path.is_file():
        return
    info = sysinfo.read_sysinfo_extended(sysinfo_path)
    ipod.sysinfo = info
    ipod.guid = sysinfo.firewire_guid(info)
    serial = info.get("SerialNumber")
    ipod.serial = serial if isinstance(serial, str) else None
    family = info.get("FamilyID")
    ipod.family_id = family if isinstance(family, int) else None
    dbver = info.get("DBVersion")
    ipod.db_version = dbver if isinstance(dbver, int) else None


def current_ipod() -> IPod | None:
    """The plugged-in iPod, mounted or not.

    Returns None when no Apple drive is present. The desktop
    environment usually mounts the device already; mount_ipod() covers
    the rest.
    """
    for device, label in _apple_partitions():
        for ipod in mounted_ipods():
            if ipod.label and ipod.label == label:
                ipod.block_device = device
                _fill_identity(ipod)
                return ipod
    # Mounted but udisks2 did not report a mount (rare): fall back to a scan.
    for ipod in mounted_ipods():
        ipod.block_device = _block_device_for(ipod.mountpoint)
        _fill_identity(ipod)
        return ipod
    return None


def auto_mount() -> IPod | None:
    """The plugged-in iPod, mounted if needed.

    Returns None when no Apple drive is present; mounts the first
    Apple partition via udisks2 when it is plugged in but unmounted.
    Raises DeviceError when the mount fails.
    """
    partitions = _apple_partitions()
    if not partitions:
        return None
    labels = {label for _device, label in partitions}
    for ipod in mounted_ipods():
        if ipod.label and ipod.label in labels:
            _fill_identity(ipod)
            return ipod
    return mount_ipod()


def mount_ipod() -> IPod:
    """Mount the Apple partition via udisks2 and return the IPod."""
    partitions = _apple_partitions()
    if not partitions:
        raise DeviceError("no Apple drive found")
    device, label = partitions[0]
    mountpoint = _get_transport().mount(device)
    ipod = next(
        (i for i in mounted_ipods() if i.label == label),
        IPod(mountpoint=Path(mountpoint) if mountpoint else _media_root() / label,
             label=label),
    )
    ipod.block_device = device
    _fill_identity(ipod)
    return ipod


def unmount_ipod(ipod: IPod) -> None:
    """Unmount the iPod via udisks2 (call after the DB is written)."""
    device = ipod.block_device or _block_device_for(ipod.mountpoint)
    if device is None:
        raise DeviceError(f"no block device for {ipod.mountpoint}")
    _get_transport().unmount(device)
