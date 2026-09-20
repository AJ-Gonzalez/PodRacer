"""iPod detection, mounting, and device identity.

Disk access goes through a Transport backend chosen by platform (see
_get_transport): udisks2 over D-Bus on Linux (see udisks2.py), the
diskutil CLI parsed with plistlib on macOS (see diskutil.py). Both
implement the five-method protocol below; no udisksctl/lsblk/
diskutil-text parsing anywhere. Direct D-Bus keeps Linux init-agnostic,
distro-agnostic, and Flatpak-sandboxable; diskutil is part of every
macOS install. The app polls `current_ipod()` from a timer; there is
no event source to subscribe to without udev, and polling every few
seconds is plenty for a device you plug in by hand.

The logic here stays testable without a display: the transport is
injected, so tests use a fake and never touch QtDBus or subprocesses.
All interpretation (Apple-vendor filter, mountpoint matching) lives in
this module, not in the transports.

Device identity comes from `iPod_Control/Device/SysInfoExtended` (see
sysinfo.py): the FireWireGUID there is the hash58 key, and the serial
numbers the model (nano 3G = 05ac:1262; libgpod maps serials to
models). The volume label is only the mount-point name, NOT the device
name the iPod shows; that lives in the master playlist title.
"""

from __future__ import annotations

import os
import pwd
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import sysinfo


class DeviceError(RuntimeError):
    """The iPod could not be detected, mounted, or read."""


@dataclass
class Partition:
    """One block device as seen through the platform transport."""

    device: str
    label: str
    vendor: str


APPLE_VENDOR = "apple"


class Transport(Protocol):
    """The disk access device.py needs; implemented by udisks2.UDisks2
    on Linux and diskutil.DiskUtil on macOS, faked in tests. Keeps all
    interpretation logic in the Qt- and subprocess-free layer."""

    def partitions(self) -> list[Partition]: ...

    def mount(self, device: str) -> str: ...

    def unmount(self, device: str) -> None: ...

    def set_label(self, device: str, label: str) -> None: ...

    def reachable(self) -> bool: ...


_transport: Transport | None = None


def _get_transport() -> Transport:
    global _transport
    if _transport is None:
        # Imported lazily: udisks2 pulls in QtDBus, which macOS never
        # needs (its transport is the diskutil subprocess wrapper).
        if sys.platform == "darwin":
            from .diskutil import DiskUtil
            _transport = DiskUtil()
        else:
            from .udisks2 import UDisks2
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
    # macOS diskarbitrationd mounts removable volumes under /Volumes
    # (no per-user path); Linux mount managers use /run/media/<user>.
    if sys.platform == "darwin":
        return Path("/Volumes")
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
    """Block device behind @mountpoint.

    Both sources are ground truth and immune to the disk manager's
    view drift (e.g. SetLabel/rename drops the old mountpoint from
    udisks2's view mid-session): kernel mountinfo on Linux (udisks2's
    own MountPoints property is an aay that PySide6 wraps unusably),
    diskutil's mountpoint lookup on macOS.
    """
    if sys.platform == "darwin":
        from . import diskutil
        return diskutil.device_for_mountpoint(mountpoint)
    return _mountinfo_device(mountpoint)


def _mountinfo_device(mountpoint: Path) -> str | None:
    try:
        text = Path("/proc/self/mountinfo").read_text()
    except OSError:
        return None
    return _parse_mountinfo(text, str(mountpoint))


def _parse_mountinfo(text: str, target: str) -> str | None:
    """Block device name behind @target, per mountinfo syntax.

    Fields: id parent major:minor root mountpoint options [..] - fstype
    source super-options; mountpoint escapes spaces as \\040.
    """
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 10:
            continue
        if parts[4].replace("\\040", " ") != target:
            continue
        try:
            source = parts[parts.index("-") + 2]
        except (ValueError, IndexError):
            continue
        if source.startswith("/dev/"):
            return source.removeprefix("/dev/")
    return None


def fill_identity(ipod: IPod) -> None:
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
                fill_identity(ipod)
                return ipod
    # Mounted but udisks2 did not report a mount (rare): fall back to a scan.
    for ipod in mounted_ipods():
        ipod.block_device = _block_device_for(ipod.mountpoint)
        fill_identity(ipod)
        return ipod
    return None


def auto_mount() -> IPod | None:
    """The plugged-in iPod, mounted if needed.

    Returns None when no Apple drive is present; mounts the first
    Apple partition via udisks2 when it is plugged in but unmounted.
    Raises DeviceError when the mount fails. The matched partition's
    block device is cached on the IPod so later device operations
    (eject, rename) never re-resolve through udisks2's changing view.
    """
    partitions = _apple_partitions()
    if not partitions:
        return None
    labels = {label: device for device, label in partitions}
    for ipod in mounted_ipods():
        if ipod.label and ipod.label in labels:
            ipod.block_device = labels[ipod.label]
            fill_identity(ipod)
            return ipod
    return mount_ipod()


def mount_ipod() -> IPod:
    """Mount the Apple partition via the platform transport and return the IPod."""
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
    fill_identity(ipod)
    return ipod


def unmount_ipod(ipod: IPod) -> None:
    """Unmount the iPod via the platform transport (after the DB is written)."""
    device = ipod.block_device or _block_device_for(ipod.mountpoint)
    if device is None:
        raise DeviceError(f"no block device for {ipod.mountpoint}")
    _get_transport().unmount(device)


def rename_label(ipod: IPod, new_label: str) -> None:
    """Rename the FAT volume label via the platform transport.

    The mount-point name follows on the next plug-in; the on-screen
    device name (master playlist title) is a separate library-state
    change. Call after renaming the library state so the two stay in
    step, but a failure here must not block the rename itself. The
    resolved block device is cached on @ipod: SetLabel/rename changes
    the disk manager's view of the filesystem, so a later
    re-resolution by mountpoint (eject) would fail.
    """
    device = ipod.block_device or _block_device_for(ipod.mountpoint)
    if device is None:
        raise DeviceError(f"no block device for {ipod.mountpoint}")
    ipod.block_device = device
    _get_transport().set_label(device, new_label)
    if sys.platform == "darwin":
        # diskutil rename renames the live volume: macOS moves the
        # mount point to /Volumes/<new label> at once, and every later
        # library write goes through ipod.mountpoint — re-resolve it
        # so the session keeps a valid path (Linux keeps the old
        # mountpoint until the next plug-in, nothing to refresh).
        from . import diskutil
        new_mp = diskutil.mountpoint_for(device)
        if new_mp is not None:
            ipod.mountpoint = new_mp
