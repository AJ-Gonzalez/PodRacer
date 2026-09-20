"""macOS transport tests: diskutil plist parsing with canned outputs.

No subprocesses run: diskutil._run is replaced with a resolver that
answers from fixture-shaped data captured on the M1 test bed (the
real `diskutil list -plist` XML, trimmed to the internal APFS disk
plus the nano). Classification, idempotency, and error mapping are
what the tests pin — diskutil itself is not mocked away.
"""

import plistlib
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from podracer import diskutil
from podracer.device import APPLE_VENDOR, Partition

# Real `diskutil list -plist` from the M1 with the nano plugged in
# (disk8, FDisk FAT32), trimmed to the internal disk plus a synthetic
# second USB stick in the same element shape.
LIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>AllDisksAndPartitions</key>
\t<array>
\t\t<dict>
\t\t\t<key>Content</key>
\t\t\t<string>GUID_partition_scheme</string>
\t\t\t<key>DeviceIdentifier</key>
\t\t\t<string>disk0</string>
\t\t\t<key>OSInternal</key>
\t\t\t<false/>
\t\t\t<key>Partitions</key>
\t\t\t<array>
\t\t\t\t<dict>
\t\t\t\t\t<key>Content</key>
\t\t\t\t\t<string>Apple_APFS_ISC</string>
\t\t\t\t\t<key>DeviceIdentifier</key>
\t\t\t\t\t<string>disk0s1</string>
\t\t\t\t\t<key>Size</key>
\t\t\t\t\t<integer>524288000</integer>
\t\t\t\t</dict>
\t\t\t\t<dict>
\t\t\t\t\t<key>Content</key>
\t\t\t\t\t<string>Apple_APFS</string>
\t\t\t\t\t<key>DeviceIdentifier</key>
\t\t\t\t\t<string>disk0s2</string>
\t\t\t\t\t<key>Size</key>
\t\t\t\t\t<integer>245107195904</integer>
\t\t\t\t</dict>
\t\t\t</array>
\t\t\t<key>Size</key>
\t\t\t<integer>251000193024</integer>
\t\t</dict>
\t\t<dict>
\t\t\t<key>Content</key>
\t\t\t<string>FDisk_partition_scheme</string>
\t\t\t<key>DeviceIdentifier</key>
\t\t\t<string>disk8</string>
\t\t\t<key>OSInternal</key>
\t\t\t<false/>
\t\t\t<key>Partitions</key>
\t\t\t<array>
\t\t\t\t<dict>
\t\t\t\t\t<key>Content</key>
\t\t\t\t\t<string>DOS_FAT_32</string>
\t\t\t\t\t<key>DeviceIdentifier</key>
\t\t\t\t\t<string>disk8s1</string>
\t\t\t\t\t<key>MountPoint</key>
\t\t\t\t\t<string>/Volumes/HYPERPINK</string>
\t\t\t\t\t<key>Size</key>
\t\t\t\t\t<integer>7951880192</integer>
\t\t\t\t\t<key>VolumeName</key>
\t\t\t\t\t<string>HYPERPINK</string>
\t\t\t\t\t<key>VolumeUUID</key>
\t\t\t\t\t<string>FABB7091-10EC-3C9E-B783-42BA330EA834</string>
\t\t\t\t</dict>
\t\t\t</array>
\t\t\t<key>Size</key>
\t\t\t<integer>7952142336</integer>
\t\t</dict>
\t\t<dict>
\t\t\t<key>Content</key>
\t\t\t<string>FDisk_partition_scheme</string>
\t\t\t<key>DeviceIdentifier</key>
\t\t\t<string>disk9</string>
\t\t\t<key>Partitions</key>
\t\t\t<array>
\t\t\t\t<dict>
\t\t\t\t\t<key>Content</key>
\t\t\t\t\t<string>DOS_FAT_32</string>
\t\t\t\t\t<key>DeviceIdentifier</key>
\t\t\t\t\t<string>disk9s1</string>
\t\t\t\t\t<key>VolumeName</key>
\t\t\t\t\t<string>STICK</string>
\t\t\t\t\t<key>VolumeUUID</key>
\t\t\t\t\t<string>11111111-1111-1111-1111-111111111111</string>
\t\t\t\t</dict>
\t\t\t</array>
\t\t</dict>
\t\t<dict>
\t\t\t<key>Content</key>
\t\t\t<string>GUID_partition_scheme</string>
\t\t\t<key>DeviceIdentifier</key>
\t\t\t<string>disk7</string>
\t\t\t<key>Partitions</key>
\t\t\t<array>
\t\t\t\t<dict>
\t\t\t\t\t<key>Content</key>
\t\t\t\t\t<string>EFI</string>
\t\t\t\t\t<key>DeviceIdentifier</key>
\t\t\t\t\t<string>disk7s1</string>
\t\t\t\t\t<key>VolumeName</key>
\t\t\t\t\t<string>EFI</string>
\t\t\t\t</dict>
\t\t\t</array>
\t\t</dict>
\t</array>
</dict>
</plist>
"""


class _FakeDiskutil:
    """Stand-in for diskutil._run: returns stdout bytes on success and
    raises DeviceError on failure, exactly like the production wrapper.
    Mount/unmount/rename mutate the canned info state the way the real
    tool does, so idempotency guards run against changing state.
    """

    def __init__(self):
        self.calls: list[tuple] = []
        self.list_dict = plistlib.loads(bytes(LIST_XML, "utf-8"))
        self.info: dict[str, dict] = {
            "disk8s1": {
                "DeviceIdentifier": "disk8s1",
                "MediaType": "iPod",
                "MountPoint": "/Volumes/HYPERPINK",
                "VolumeName": "HYPERPINK",
            },
            "disk9s1": {
                "DeviceIdentifier": "disk9s1",
                "MediaType": "Generic External",
                "MountPoint": "",
                "VolumeName": "STICK",
            },
            "unmounted_ipod": {
                "DeviceIdentifier": "disk10s1",
                "MediaType": "iPod",
                "MountPoint": "",
                "VolumeName": "MULE",
            },
            "/Volumes/HYPERPINK": {
                "DeviceIdentifier": "disk8s1",
                "MediaType": "iPod",
                "MountPoint": "/Volumes/HYPERPINK",
            },
        }

    def __call__(self, *args: str):
        # diskutil._run(*args) passes the subcommand directly; args
        # looks like ("info", "-plist", "disk8s1").
        cmd = args[0]
        self.calls.append(args)
        if cmd == "list":
            return plistlib.dumps(self.list_dict)
        if cmd == "info":
            info = self.info.get(args[2])
            if info is None:
                raise diskutil.DeviceError(
                    f"info failed: Could not find disk: {args[2]}"
                )
            return plistlib.dumps(info)
        if cmd == "mount":
            self.info[args[1]]["MountPoint"] = "/Volumes/HYPERPINK"
            return b"Volume HYPERPINK on disk8s1 mounted\n"
        if cmd == "unmount":
            self.info[args[1]]["MountPoint"] = ""
            return b"Unmounted disk8s1\n"
        if cmd == "rename":
            self.info[args[1]]["VolumeName"] = args[2]
            return b"Renamed\n"
        raise diskutil.DeviceError(
            f"{cmd} failed: unexpected command {' '.join(args)}"
        )

    def count(self, cmd):
        return sum(1 for args in self.calls if args[0] == cmd)


def _transport(fake):
    return mock.patch.object(diskutil, "_run", side_effect=fake)


class PartitionsTests(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeDiskutil()
        mock.patch.object(diskutil, "_run", self.fake).start()
        self.addCleanup(mock.patch.stopall)

    def test_finds_the_ipod_and_skips_the_rest(self):
        out = diskutil.DiskUtil().partitions()
        self.assertEqual(out, [
            Partition("disk8s1", "HYPERPINK", APPLE_VENDOR),
        ])
        # Only filesystem-carrying non-EFI partitions reach diskutil
        # info: disk0 (APFS, no names) and disk7s1 (EFI) are skipped.
        self.assertEqual(self.fake.count("info"), 2)
        info_targets = [argv[2] for argv in self.fake.calls if argv[0] == "info"]
        self.assertEqual(set(info_targets), {"disk8s1", "disk9s1"})

    def test_vendor_verdict_is_memoized(self):
        t = diskutil.DiskUtil()
        t.partitions()
        self.assertEqual(self.fake.count("info"), 2)
        t.partitions()
        self.assertEqual(self.fake.count("info"), 2)  # no new info calls
        self.assertEqual(self.fake.count("list"), 2)

    def test_reused_identifier_does_not_inherit_the_verdict(self):
        t = diskutil.DiskUtil()
        self.assertEqual(t.partitions(), [
            Partition("disk8s1", "HYPERPINK", APPLE_VENDOR),
        ])
        # The iPod leaves the system: its whole disk drops out of the
        # listing and the cache entry is purged with it.
        disks = self.fake.list_dict["AllDisksAndPartitions"]
        self.fake.list_dict["AllDisksAndPartitions"] = [
            d for d in disks if d.get("DeviceIdentifier") != "disk8"
        ]
        self.assertEqual(t.partitions(), [])
        # A generic FAT stick then re-enumerates on the freed diskN —
        # it must be classified fresh, not reuse the iPod verdict.
        self.fake.list_dict["AllDisksAndPartitions"].append({
            "DeviceIdentifier": "disk8",
            "Content": "FDisk_partition_scheme",
            "Partitions": [{
                "Content": "DOS_FAT_32",
                "DeviceIdentifier": "disk8s1",
                "VolumeName": "OTHERS",
                "VolumeUUID": "22222222-2222-2222-2222-222222222222",
            }],
        })
        self.fake.info["disk8s1"] = {
            "DeviceIdentifier": "disk8s1",
            "MediaType": "Generic External",
            "MountPoint": "",
            "VolumeName": "OTHERS",
        }
        self.assertEqual(t.partitions(), [])


class MountLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeDiskutil()
        mock.patch.object(diskutil, "_run", self.fake).start()
        self.addCleanup(mock.patch.stopall)
        self.t = diskutil.DiskUtil()

    def test_mount_returns_mountpoint_without_remounting(self):
        self.assertEqual(self.t.mount("disk8s1"), "/Volumes/HYPERPINK")
        self.assertEqual(self.fake.count("mount"), 0)

    def test_mount_runs_diskutil_when_unmounted(self):
        self.fake.info["disk8s1"]["MountPoint"] = ""
        self.assertEqual(self.t.mount("disk8s1"), "/Volumes/HYPERPINK")
        self.assertEqual(self.fake.count("mount"), 1)

    def test_unmount_skips_already_unmounted_volume(self):
        self.t.unmount("disk9s1")  # MountPoint already ""
        self.assertEqual(self.fake.count("unmount"), 0)
        self.t.unmount("disk8s1")  # mounted: unmount runs
        self.assertEqual(self.fake.count("unmount"), 1)

    def test_unmount_timeout_that_still_lands_reads_as_success(self):
        fake = _FakeDiskutil()

        def run(*args):
            if args[0] == "unmount":
                fake.info["disk8s1"]["MountPoint"] = ""  # it landed
                raise diskutil.DeviceError("unmount timed out")
            return fake(*args)

        with mock.patch.object(diskutil, "_run", run):
            diskutil.DiskUtil().unmount("disk8s1")  # no raise

    def test_mount_timeout_that_still_lands_reads_as_success(self):
        fake = _FakeDiskutil()
        fake.info["disk8s1"]["MountPoint"] = ""

        def run(*args):
            if args[0] == "mount":
                fake.info["disk8s1"]["MountPoint"] = "/Volumes/HYPERPINK"
                raise diskutil.DeviceError("mount timed out")
            return fake(*args)

        with mock.patch.object(diskutil, "_run", run):
            self.assertEqual(
                diskutil.DiskUtil().mount("disk8s1"), "/Volumes/HYPERPINK"
            )

    def test_unmount_failure_when_volume_still_mounted_raises(self):
        fake = _FakeDiskutil()

        def run(*args):
            if args[0] == "unmount":
                raise diskutil.DeviceError("unmount failed: in use")
            return fake(*args)

        with mock.patch.object(diskutil, "_run", run):
            with self.assertRaises(diskutil.DeviceError):
                diskutil.DiskUtil().unmount("disk8s1")

    def test_set_label_noop_on_same_name(self):
        self.t.set_label("disk8s1", "HYPERPINK")
        self.assertEqual(self.fake.count("rename"), 0)
        self.t.set_label("disk8s1", "STONER")
        self.assertEqual(self.fake.count("rename"), 1)
        self.assertEqual(self.fake.calls[-1], ("rename", "disk8s1", "STONER"))

    def test_mountpoint_and_device_resolution(self):
        self.assertEqual(
            diskutil.device_for_mountpoint(Path("/Volumes/HYPERPINK")),
            "disk8s1",
        )
        self.assertEqual(
            diskutil.mountpoint_for("disk8s1"), Path("/Volumes/HYPERPINK")
        )
        self.assertIsNone(diskutil.mountpoint_for("unmounted_ipod"))


class ErrorMappingTests(unittest.TestCase):
    """Production _run behavior: tool exit codes and timeouts become
    DeviceError. Tested by patching subprocess.run itself."""

    def test_nonzero_exit_maps_to_device_error_with_tool_stderr(self):
        proc = subprocess.CompletedProcess([], returncode=1, stdout=b"",
                                           stderr=b"disk8s1 is in use")
        with mock.patch.object(diskutil.subprocess, "run",
                               return_value=proc):
            with self.assertRaises(diskutil.DeviceError) as ctx:
                diskutil._run("mount", "disk8s1")
        self.assertIn("disk8s1 is in use", str(ctx.exception))

    def test_stderr_missing_falls_back_to_stdout(self):
        proc = subprocess.CompletedProcess([], returncode=1,
                                           stdout=b"nothing happened",
                                           stderr=b"")
        with mock.patch.object(diskutil.subprocess, "run",
                               return_value=proc):
            with self.assertRaises(diskutil.DeviceError) as ctx:
                diskutil._run("mount", "disk8s1")
        self.assertIn("nothing happened", str(ctx.exception))

    def test_timeout_maps_to_device_error(self):
        def hang(argv, **kwargs):
            raise subprocess.TimeoutExpired(cmd="diskutil", timeout=10)

        with mock.patch.object(diskutil.subprocess, "run", hang):
            with self.assertRaises(diskutil.DeviceError) as ctx:
                diskutil._run("mount", "disk8s1")
        self.assertIn("timed out", str(ctx.exception))


class PropagationTests(unittest.TestCase):
    """Transport errors surface through the class API unchanged."""

    def test_diskutil_failure_raises_device_error(self):
        fake = _FakeDiskutil()
        with mock.patch.object(diskutil, "_run", fake):
            with self.assertRaises(diskutil.DeviceError):
                diskutil.device_for_mountpoint(Path("/Volumes/NOPE"))

    def test_mount_failure_raises_with_tool_message(self):
        fake = _FakeDiskutil()
        fake.info["disk8s1"]["MountPoint"] = ""  # force the mount attempt

        def run(*args):
            if args[0] == "mount":
                raise diskutil.DeviceError("mount failed: disk8s1 is in use")
            return fake(*args)

        with mock.patch.object(diskutil, "_run", run):
            with self.assertRaises(diskutil.DeviceError) as ctx:
                diskutil.DiskUtil().mount("disk8s1")
        self.assertIn("disk8s1 is in use", str(ctx.exception))


class ReachableTests(unittest.TestCase):
    def test_diskutil_is_part_of_the_install(self):
        self.assertTrue(diskutil.DiskUtil().reachable())


if __name__ == "__main__":
    unittest.main()
