"""Test package bootstrap: put src/ on sys.path for the flat test layout.

Keeps `python3 -m unittest discover -s tests` working with the src/
layout without PYTHONPATH gymnastics.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
