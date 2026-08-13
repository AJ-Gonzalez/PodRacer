"""udisks2 transport over D-Bus (QtDBus).

device.py talks to the udisks2 daemon through this class instead of
shelling out to udisksctl/lsblk: direct D-Bus works inside a Flatpak
sandbox (with --socket=system-bus), on any init system, and on any
distro that runs the udisks2 daemon. Only the manager, block, drive,
and filesystem interfaces are used, with synchronous calls, so no
event loop is needed beyond the app's own.

Thin adapter on purpose: all interpretation (Apple vendor filter,
mountpoint matching) lives in device.py so tests can fake the
transport without D-Bus.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

SERVICE = "org.freedesktop.UDisks2"
MANAGER_PATH = "/org/freedesktop/UDisks2"
BLOCK_DEVICES = "/org/freedesktop/UDisks2/block_devices"


class DeviceError(RuntimeError):
    """The iPod could not be detected, mounted, or read."""


@dataclass
class Partition:
    """One block device as seen through udisks2."""

    device: str
    label: str
    vendor: str


def _interface(object_path: str, interface: str) -> QDBusInterface:
    return QDBusInterface(SERVICE, object_path, interface,
                          QDBusConnection.systemBus())


def _is_ok(msg: QDBusMessage) -> bool:
    return msg.type() == QDBusMessage.MessageType.ReplyMessage


class UDisks2:
    """udisks2 D-Bus client: block listing, mount, unmount."""

    def partitions(self) -> list[Partition]:
        out: list[Partition] = []
        for path in self._block_paths():
            block = _interface(path, "org.freedesktop.UDisks2.Block")
            drive_path = str(block.property("Drive") or "/")
            vendor = ""
            if drive_path not in ("", "/"):
                drive = _interface(drive_path, "org.freedesktop.UDisks2.Drive")
                vendor = str(drive.property("Vendor") or "")
            out.append(Partition(
                device=path.rsplit("/", 1)[-1],
                label=str(block.property("IdLabel") or ""),
                vendor=vendor,
            ))
        return out

    def block_device_for(self, mountpoint: Path) -> str | None:
        target = str(mountpoint)
        for path in self._block_paths():
            fs = _interface(path, "org.freedesktop.UDisks2.Filesystem")
            if target in self._mountpoints(fs):
                return path.rsplit("/", 1)[-1]
        return None

    def mount(self, device: str) -> str:
        fs = self._filesystem(device)
        msg = fs.call("Mount", {}, "")
        if not _is_ok(msg):
            raise DeviceError(f"mount failed: {msg.errorMessage()}")
        return str(msg.arguments()[0] or "")

    def unmount(self, device: str) -> None:
        fs = self._filesystem(device)
        msg = fs.call("Unmount", {})
        if not _is_ok(msg):
            raise DeviceError(f"unmount failed: {msg.errorMessage()}")

    def reachable(self) -> bool:
        conn = QDBusConnection.systemBus()
        if not conn.isConnected():
            return False
        manager = _interface(MANAGER_PATH, "org.freedesktop.UDisks2.Manager")
        return _is_ok(manager.call("GetBlockDevices", {}))

    # -- internals ------------------------------------------------------

    @staticmethod
    def _block_path(device: str) -> str:
        return f"{BLOCK_DEVICES}/{device}"

    def _filesystem(self, device: str) -> QDBusInterface:
        return _interface(self._block_path(device),
                          "org.freedesktop.UDisks2.Filesystem")

    def _block_paths(self) -> list[str]:
        manager = _interface(MANAGER_PATH, "org.freedesktop.UDisks2.Manager")
        msg = manager.call("GetBlockDevices", {})
        if not _is_ok(msg):
            raise DeviceError(f"udisks2 not reachable: {msg.errorMessage()}")
        return [str(p) for p in msg.arguments()[0]]

    @staticmethod
    def _mountpoints(fs: QDBusInterface) -> list[str]:
        value = fs.property("MountPoints")
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for raw in value:
            try:
                out.append(bytes(raw).decode("utf-8", "replace"))
            except (TypeError, ValueError):
                continue
        return out
