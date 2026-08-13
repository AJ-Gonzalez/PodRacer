"""udisks2 transport tests: manager-object discovery (mocked D-Bus).

udisks2 2.11 moved the Manager interface from the root object to
/org/freedesktop/UDisks2/Manager; older releases keep it on the root.
Discovery introspects the live daemon, so the transport works on both
layouts and any init system, without a live bus in tests.
"""

import unittest
from unittest import mock

from PySide6.QtDBus import QDBusMessage

import podracer.udisks2 as udisks2


class _FakeInterface:
    def __init__(self, msg):
        self._msg = msg

    def call(self, *args):
        return self._msg


class _FakeMessage:
    def __init__(self, ok, args=()):
        self._ok = ok
        self._args = args

    def type(self):
        return (QDBusMessage.MessageType.ReplyMessage if self._ok
                else QDBusMessage.MessageType.ErrorMessage)

    def arguments(self):
        return list(self._args)


class ManagerDiscoveryTests(unittest.TestCase):
    def tearDown(self):
        udisks2._manager_path = None

    def _discover(self, message):
        with mock.patch.object(udisks2, "_interface",
                               return_value=_FakeInterface(message)):
            return udisks2._manager_object_path()

    def test_new_layout_manager_on_child_object(self):
        xml = (
            '<node name="/org/freedesktop/UDisks2">'
            '<interface name="org.freedesktop.DBus.Introspectable"/>'
            '<node name="block_devices"/>'
            '<node name="Manager"/>'
            "</node>"
        )
        self.assertEqual(
            self._discover(_FakeMessage(True, args=(xml,))),
            "/org/freedesktop/UDisks2/Manager",
        )

    def test_classic_layout_manager_on_root(self):
        xml = (
            '<node name="/org/freedesktop/UDisks2">'
            '<interface name="org.freedesktop.UDisks2.Manager"/>'
            '<node name="block_devices"/>'
            "</node>"
        )
        self.assertEqual(
            self._discover(_FakeMessage(True, args=(xml,))),
            "/org/freedesktop/UDisks2",
        )

    def test_discovery_failure_falls_back_to_classic_path(self):
        self.assertEqual(
            self._discover(_FakeMessage(False)),
            "/org/freedesktop/UDisks2",
        )


if __name__ == "__main__":
    unittest.main()
