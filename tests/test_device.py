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
        # The hash58 key, exactly as the codec tests use it.
        self.assertEqual(info["FireWireGUID"], "000A27001BB9E492")
        self.assertEqual(sysinfo.firewire_guid(info), "000A27001BB9E492")
        self.assertEqual(info["SerialNumber"], "YM825HUD13F")
        self.assertEqual(info["FamilyID"], 12)
        self.assertEqual(info["DBVersion"], 3)

    def test_ignores_nested_keys_without_dicts(self):
        # Apple's ImageSpecifications arrays hold bare <key> elements
        # that break plistlib; the scanner must not choke on them.
        text = """
        <?xml version="1.0"?><plist version="1.0"><dict>
        <key>FireWireGUID</key><string>000A27001BB9E492</string>
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
        self.assertEqual(info["FireWireGUID"], "000A27001BB9E492")
        self.assertEqual(info["MaxTracks"], 65534)
        self.assertEqual(info["CanHibernate"], False)
        self.assertEqual(info["RentalClockBias"], 2.5)

    def test_bad_guid_rejected(self):
        self.assertIsNone(sysinfo.firewire_guid({"FireWireGUID": "nope"}))
        self.assertIsNone(sysinfo.firewire_guid({}))




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

    def test_apple_partitions_filter(self):
        lsblk = [
            {"name": "sda", "vendor": None, "children": []},
            {
                "name": "sdb",
                "vendor": "Apple   ",
                "model": "iPod",
                "children": [
                    {"name": "sdb1", "label": "HYPERPINK", "mountpoint": "/run/media/u/HYPERPINK"},
                ],
            },
            {"name": "sdc", "vendor": "SanDisk", "children": []},
        ]
        self.assertEqual(
            device._apple_partitions(lsblk), [("sdb1", "HYPERPINK")]
        )

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
