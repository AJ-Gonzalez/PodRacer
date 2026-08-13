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

import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtDBus import (
    QDBusArgument,
    QDBusConnection,
    QDBusInterface,
    QDBusMessage,
    QDBusObjectPath,
)

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


def _unwrap(value):
    """Convert a QDBusObjectPath to its path string.

    QDBusObjectPath has no useful __str__ (it returns the repr).
    Deliberately the only unwrap: PySide6's QDBusArgument read API is
    a trap (begin* emits "write from a read-only object" and asVariant
    without it returns the container itself, recursing), so the
    transport reads no compound D-Bus types at all: block listing comes
    from Introspect XML strings and mountpoint resolution from kernel
    mountinfo (see device.py).
    """
    if isinstance(value, QDBusObjectPath):
        return value.path()
    return value


_manager_path: str | None = None


def _manager_object_path() -> str:
    """Path of the object exposing org.freedesktop.UDisks2.Manager.

    udisks2 2.11 moved the Manager interface from the root object
    (/org/freedesktop/UDisks2) to /org/freedesktop/UDisks2/Manager;
    older releases keep it on the root. Discover via Introspect XML
    (a plain string, unlike GetManagedObjects which PySide6 hands back
    as a QDBusArgument); fall back to the classic path on failure.
    """
    global _manager_path
    if _manager_path is not None:
        return _manager_path
    manager = MANAGER_PATH
    root = _interface(MANAGER_PATH, "org.freedesktop.DBus.Introspectable")
    msg = root.call("Introspect")
    if _is_ok(msg):
        xml = str(msg.arguments()[0])
        if re.search(r'<node name="Manager"[ />]', xml):
            manager = f"{MANAGER_PATH}/Manager"
        elif 'interface name="org.freedesktop.UDisks2.Manager"' in xml:
            manager = MANAGER_PATH
    _manager_path = manager
    return manager


class UDisks2:
    """udisks2 D-Bus client: block listing, mount, unmount."""

    def partitions(self) -> list[Partition]:
        out: list[Partition] = []
        for path in self._block_paths():
            block = _interface(path, "org.freedesktop.UDisks2.Block")
            drive_path = _unwrap(block.property("Drive")) or "/"
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

    def set_label(self, device: str, label: str) -> None:
        """Rename the filesystem volume label (FAT label for the iPod)."""
        fs = self._filesystem(device)
        msg = fs.call("SetLabel", label, {})
        if not _is_ok(msg):
            raise DeviceError(f"rename label failed: {msg.errorMessage()}")

    def reachable(self) -> bool:
        conn = QDBusConnection.systemBus()
        if not conn.isConnected():
            return False
        manager = _interface(_manager_object_path(),
                             "org.freedesktop.UDisks2.Manager")
        return _is_ok(manager.call("GetBlockDevices", {}))

    # -- internals ------------------------------------------------------

    @staticmethod
    def _block_path(device: str) -> str:
        return f"{BLOCK_DEVICES}/{device}"

    def _filesystem(self, device: str) -> QDBusInterface:
        return _interface(self._block_path(device),
                          "org.freedesktop.UDisks2.Filesystem")

    def _block_paths(self) -> list[str]:
        """Block device object paths via Introspect XML.

        GetBlockDevices returns an array-of-object-paths, which PySide6
        wraps in a QDBusArgument whose read API is unusable without
        spurious warnings; the Introspect XML walk returns plain
        strings and lists the same devices.
        """
        node = _interface(BLOCK_DEVICES, "org.freedesktop.DBus.Introspectable")
        msg = node.call("Introspect")
        if not _is_ok(msg):
            raise DeviceError(f"udisks2 not reachable: {msg.errorMessage()}")
        xml = str(msg.arguments()[0])
        return [
            f"{BLOCK_DEVICES}/{name}"
            for name in re.findall(r'<node name="([^"]+)"', xml)
        ]
