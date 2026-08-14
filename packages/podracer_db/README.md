# podracer_db

Pure-stdlib iTunesDB codec for the classic iPod family (nano 1G-3G,
classic 1G-5.5G, mini). Parse and write the database with zero
dependencies.

```python
from pathlib import Path
from podracer_db import parse_db, write_db

lib = parse_db(Path("iTunesDB").read_bytes())
for track in lib.tracks:
    print(track.artist or "Unknown", "-", track.display_title)

db_bytes = write_db(lib, firewire_guid="0011223344556677")
```

The write side is hardware-verified: a PodRacer-written DB boots on a
real nano 3G with its full library, and the codec round-trips the
device's own DB byte-for-byte.
