"""Tests for the tolerant SysInfoExtended plist reader and the device
detection layer. Plist tests run against the real device fixture;
device tests use fake trees and injected lsblk JSON (no hardware).
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from podracer import device, sysinfo

RAW = Path(
    os.environ.get(
        "IPOD_THINGY_FIXTURES",
        Path(__file__).resolve().parent.parent / "fixtures" / "raw",
    )
)


class SysInfoTests(unittest.TestCase):
    def test_parses_real_device_plist(self):
        path = RAW / "SysInfoExtended"
        if not path.is_file():
            self.skipTest("no extracted fixtures; run scripts/extract_fixtures.py")
        info = sysinfo.read_sysinfo_extended(path)
        # The hash58 key, exactly as the codec tests use it. The real
        # GUID/serial are hardware-identifying and live only in the
        # gitignored tests/.fixture_guid file.
        lines = (Path(__file__).resolve().parent / ".fixture_guid")
        guid, serial = lines.read_text().splitlines()[:2]
        self.assertEqual(info["FireWireGUID"], guid)
        self.assertEqual(sysinfo.firewire_guid(info), guid)
        self.assertEqual(info["SerialNumber"], serial)
        self.assertEqual(info["FamilyID"], 12)
        self.assertEqual(info["DBVersion"], 3)

    def test_ignores_nested_keys_without_dicts(self):
        # Apple's ImageSpecifications arrays hold bare <key> elements
        # that break plistlib; the scanner must not choke on them.
        text = """
        <?xml version="1.0"?><plist version="1.0"><dict>
        <key>FireWireGUID</key><string>0011223344556677</string>
        <key>ImageSpecifications</key>
        <array>
        <key>1067</key>
        <dict><key>FormatId</key><integer>1067</integer></dict>
        </array>
        <key>MaxTracks</key><integer>65534</integer>
        <key>CanHibernate</key><false/>
        <key>RentalClockBias</key><real>2.5</real>
        </dict></plist>
        """
        info = sysinfo.parse_sysinfo_extended(text)
        self.assertEqual(info["FireWireGUID"], "0011223344556677")
        self.assertEqual(info["MaxTracks"], 65534)
        self.assertEqual(info["CanHibernate"], False)
        self.assertEqual(info["RentalClockBias"], 2.5)

    def test_bad_guid_rejected(self):
        self.assertIsNone(sysinfo.firewire_guid({"FireWireGUID": "nope"}))
        self.assertIsNone(sysinfo.firewire_guid({}))




class FakeTransport:
    """Canned udisks2 transport for device tests (no D-Bus, no Qt)."""

    def __init__(self, partitions=(), mount_result="/run/media/u/HYPERPINK"):
        self._partitions = list(partitions)
        self.mount_result = mount_result
        self.mounted: list[str] = []
        self.unmounted: list[str] = []
        self.labels: list[tuple[str, str]] = []

    def partitions(self):
        return list(self._partitions)

    def mount(self, device):
        self.mounted.append(device)
        return self.mount_result

    def unmount(self, device):
        self.unmounted.append(device)

    def set_label(self, device, label):
        self.labels.append((device, label))

    def reachable(self):
        return True


class DeviceTests(unittest.TestCase):
    def test_mounted_ipods_finds_ipod_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "HYPERPINK" / "iPod_Control").mkdir(parents=True)
            (root / "USB_STICK").mkdir()  # not an iPod
            found = device.mounted_ipods(root)
            self.assertEqual([p.mountpoint.name for p in found], ["HYPERPINK"])

    def test_mounted_ipods_empty_without_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(device.mounted_ipods(Path(tmp)), [])

    def test_apple_partitions_filters_vendor(self):
        fake = FakeTransport(partitions=[
            device.Partition("sdb1", "HYPERPINK", "Apple"),
            device.Partition("sdb2", "RECOVERY", "Apple   "),
            device.Partition("sdc1", "STICK", "SanDisk"),
        ])
        with mock.patch.object(device, "_get_transport", return_value=fake):
            self.assertEqual(
                device._apple_partitions(),
                [("sdb1", "HYPERPINK"), ("sdb2", "RECOVERY")],
            )

    def test_parse_mountinfo_finds_device(self):
        text = (
            "36 35 98:0 / / rw,relatime shared:1 - ext4 /dev/sda2 rw\n"
            "40 36 98:1 / /run/media/alicia/HYPERPINK rw,nosuid "
            "shared:2 - vfat /dev/sdb1 rw\n"
        )
        self.assertEqual(
            device._parse_mountinfo(text, "/run/media/alicia/HYPERPINK"),
            "sdb1",
        )
        self.assertEqual(device._parse_mountinfo(text, "/"), "sda2")
        self.assertIsNone(device._parse_mountinfo(text, "/mnt/nowhere"))

    def test_block_device_for_uses_mountinfo(self):
        with mock.patch.object(
            device, "_mountinfo_device", return_value="sdb1"
        ):
            self.assertEqual(
                device._block_device_for(Path("/run/media/u/HYPERPINK")),
                "sdb1",
            )

    def test_mount_ipod_uses_transport(self):
        fake = FakeTransport(partitions=[
            device.Partition("sdb1", "HYPERPINK", "Apple"),
        ])
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(device, "_get_transport", return_value=fake), \
             mock.patch.object(device, "mounted_ipods", return_value=[]):
            ipod = device.mount_ipod()
            self.assertEqual(fake.mounted, ["sdb1"])
            self.assertEqual(ipod.block_device, "sdb1")
            self.assertEqual(ipod.label, "HYPERPINK")
            self.assertEqual(ipod.mountpoint, Path(fake.mount_result))

    def test_mount_ipod_no_drive_raises(self):
        fake = FakeTransport(partitions=[])
        with mock.patch.object(device, "_get_transport", return_value=fake):
            with self.assertRaises(device.DeviceError):
                device.mount_ipod()

    def test_unmount_ipod_uses_transport(self):
        fake = FakeTransport()
        ipod = device.IPod(mountpoint=Path("/run/media/u/HYPERPINK"),
                           block_device="sdb1")
        with mock.patch.object(device, "_get_transport", return_value=fake):
            device.unmount_ipod(ipod)
        self.assertEqual(fake.unmounted, ["sdb1"])

    def test_unmount_ipod_resolves_device_via_mountinfo(self):
        fake = FakeTransport()
        ipod = device.IPod(mountpoint=Path("/run/media/u/HYPERPINK"))
        with mock.patch.object(device, "_get_transport", return_value=fake), \
             mock.patch.object(device, "_mountinfo_device",
                               return_value="sdb1"):
            device.unmount_ipod(ipod)
        self.assertEqual(fake.unmounted, ["sdb1"])

    def test_rename_label_uses_transport(self):
        fake = FakeTransport()
        ipod = device.IPod(mountpoint=Path("/run/media/u/HYPERPINK"),
                           block_device="sdb1")
        with mock.patch.object(device, "_get_transport", return_value=fake):
            device.rename_label(ipod, "STONER")
        self.assertEqual(fake.labels, [("sdb1", "STONER")])

    def test_rename_label_caches_block_device(self):
        fake = FakeTransport()
        ipod = device.IPod(mountpoint=Path("/run/media/u/HYPERPINK"))
        with mock.patch.object(device, "_get_transport", return_value=fake), \
             mock.patch.object(device, "_mountinfo_device",
                               return_value="sdb1"):
            device.rename_label(ipod, "STONER")
        self.assertEqual(ipod.block_device, "sdb1")
        self.assertEqual(fake.labels, [("sdb1", "STONER")])

    def test_current_ipod_matches_mount_by_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "HYPERPINK" / "iPod_Control" / "iTunes").mkdir(parents=True)
            lsblk = [
                {
                    "name": "sdb",
                    "vendor": "Apple   ",
                    "children": [
                        {"name": "sdb1", "label": "HYPERPINK",
                         "mountpoint": str(root / "HYPERPINK")},
                    ],
                }
            ]
            with mock.patch.object(device, "_apple_partitions",
                                   return_value=[("sdb1", "HYPERPINK")]), \
                 mock.patch.object(device, "mounted_ipods",
                                   return_value=device.mounted_ipods(root)):
                ipod = device.current_ipod()
                self.assertIsNotNone(ipod)
                self.assertEqual(ipod.block_device, "sdb1")
                self.assertEqual(ipod.mountpoint, root / "HYPERPINK")

    def test_auto_mount_no_drive_returns_none(self):
        with mock.patch.object(device, "_apple_partitions", return_value=[]), \
             mock.patch.object(device, "mount_ipod") as mount:
            self.assertIsNone(device.auto_mount())
            mount.assert_not_called()

    def test_auto_mount_mounted_drive_not_remounted(self):
        ipod = device.IPod(mountpoint=Path("/run/media/u/HYPERPINK"),
                           label="HYPERPINK")
        with mock.patch.object(device, "_apple_partitions",
                               return_value=[("sdb1", "HYPERPINK")]), \
             mock.patch.object(device, "mounted_ipods", return_value=[ipod]), \
             mock.patch.object(device, "mount_ipod") as mount:
            found = device.auto_mount()
            self.assertIs(found, ipod)
            self.assertEqual(found.block_device, "sdb1")
            mount.assert_not_called()

    def test_auto_mount_mounts_unmounted_drive(self):
        mounted = device.IPod(mountpoint=Path("/run/media/u/HYPERPINK"),
                              label="HYPERPINK")
        with mock.patch.object(device, "_apple_partitions",
                               return_value=[("sdb1", "HYPERPINK")]), \
             mock.patch.object(device, "mounted_ipods", return_value=[]), \
             mock.patch.object(device, "mount_ipod", return_value=mounted) as mount:
            found = device.auto_mount()
            self.assertIs(found, mounted)
            mount.assert_called_once()


if __name__ == "__main__":
    unittest.main()
