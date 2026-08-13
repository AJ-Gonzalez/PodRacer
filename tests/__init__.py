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
