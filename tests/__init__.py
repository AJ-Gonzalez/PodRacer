"""Test package bootstrap: put the src trees on sys.path for the flat
test layout.

Keeps `python3 -m unittest discover -s tests` working with the src/
layout without PYTHONPATH gymnastics. The codec lives in its own
package tree (packages/podracer_db/src); the app stays in src/.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for src in (ROOT / "src", ROOT / "packages" / "podracer_db" / "src"):
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

# Unit tests must never touch the real disk layer: MainWindow's
# constructor polls the device layer immediately, and without a stub
# every UI test would run the platform's real disk tools and could
# auto-detect a plugged-in iPod on the test machine. Tests that
# exercise device behavior inject their own fakes (see test_device).
import podracer.device as _device


class _NoDiskTransport:
    """Suite-wide stand-in: no Apple media, no mount operations."""

    def partitions(self):
        return []

    def mount(self, device):
        return ""

    def unmount(self, device):
        pass

    def set_label(self, device, label):
        pass

    def reachable(self):
        return True


_device._transport = _NoDiskTransport()
