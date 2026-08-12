"""iPod detection, mounting, and device identity.

Everything here is Qt-free and works off two external binaries:
`lsblk` (detection: vendor/model/mountpoint) and `udisksctl`
(mount/unmount). The app polls `current_ipod()` from a timer; there is
no event source to subscribe to without pyudev, and polling every few
seconds is plenty for a device you plug in by hand.

Device identity comes from `iPod_Control/Device/SysInfoExtended` (see
sysinfo.py): the FireWireGUID there is the hash58 key, and the serial
numbers the model (nano 3G = 05ac:1262; libgpod maps serials to
models). The volume label is only the mount-point name, NOT the device
name the iPod shows — that lives in the master playlist title.
"""

from __future__ import annotations

import json
import os
import pwd
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import sysinfo

APPLE_VENDOR = "apple"


class DeviceError(RuntimeError):
    """The iPod could not be detected, mounted, or read."""


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
    sysinfo: dict = field(default_factory=dict)

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


def _lsblk_json() -> list[dict]:
    try:
        proc = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,VENDOR,MODEL,LABEL,MOUNTPOINT,FSTYPE"],
            capture_output=True, text=True, check=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        raise DeviceError(f"lsblk failed: {exc}") from exc
    return json.loads(proc.stdout)["blockdevices"]


def _apple_partitions(lsblk: list[dict] | None = None) -> list[tuple[str, str]]:
    """(block device, label) for every partition of an Apple drive."""
    out: list[tuple[str, str]] = []
    for drive in lsblk if lsblk is not None else _lsblk_json():
        vendor = (drive.get("vendor") or "").strip().lower()
        if vendor != APPLE_VENDOR:
            continue
        for child in drive.get("children") or []:
            out.append((child["name"], child.get("label") or ""))
    return out


def _block_device_for(mountpoint: Path) -> str | None:
    for drive in _lsblk_json():
        for child in drive.get("children") or []:
            if child.get("mountpoint") == str(mountpoint):
                return child["name"]
    return None


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
    # Mounted but lsblk did not see it (rare): fall back to a scan.
    for ipod in mounted_ipods():
        ipod.block_device = _block_device_for(ipod.mountpoint)
        _fill_identity(ipod)
        return ipod
    return None


def auto_mount() -> IPod | None:
    """The plugged-in iPod, mounted if needed.

    Returns None when no Apple drive is present; mounts the first
    Apple partition via udisksctl when it is plugged in but unmounted.
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
    """Mount the Apple partition via udisksctl and return the IPod."""
    partitions = _apple_partitions()
    if not partitions:
        raise DeviceError("no Apple drive found")
    device, label = partitions[0]
    if not shutil.which("udisksctl"):
        raise DeviceError("udisksctl not found; cannot mount the iPod")
    try:
        subprocess.run(
            ["udisksctl", "mount", "-b", f"/dev/{device}"],
            capture_output=True, text=True, check=True, timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        raise DeviceError(
            f"udisksctl mount failed: {exc.stderr.strip() or exc}"
        ) from exc
    ipod = next(
        (i for i in mounted_ipods() if i.label == label),
        IPod(mountpoint=_media_root() / label, label=label),
    )
    ipod.block_device = device
    _fill_identity(ipod)
    return ipod


def unmount_ipod(ipod: IPod) -> None:
    """Unmount the iPod via udisksctl (call after the DB is written)."""
    if not shutil.which("udisksctl"):
        raise DeviceError("udisksctl not found; cannot unmount the iPod")
    device = ipod.block_device or _block_device_for(ipod.mountpoint)
    if device is None:
        raise DeviceError(f"no block device for {ipod.mountpoint}")
    try:
        subprocess.run(
            ["udisksctl", "unmount", "-b", f"/dev/{device}"],
            capture_output=True, text=True, check=True, timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        raise DeviceError(
            f"udisksctl unmount failed: {exc.stderr.strip() or exc}"
        ) from exc
