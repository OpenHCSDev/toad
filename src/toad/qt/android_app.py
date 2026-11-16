"""The APK's app folder, and the process environment the APK runs in.

tools/android/assemble.py lays the app folder out with this package at its root, beside the
files named below. The APK's `main.py` (tools/android/main.py) calls `enter` before it
imports anything else, because the libraries it sets up read the environment when they are
imported:

- the compiled speedups of aiohttp, multidict, yarl, frozenlist and propcache are not
  shipped, so each runs its pure-Python implementation;
- Python's ssl looks for /etc/ssl/cert.pem, which Android lacks (and Android's own store is
  named by OpenSSL's old subject hash), so the app carries certifi's CA bundle;
- Toad's default theme is pywal's palette, and the app carries the desktop's colors.json;
- Toad's database (saved tabs) and the held bus profiles, which agent-comms keeps under the
  home directory, live in the app's own storage.

Importing this module changes nothing. Only the APK's own process enters the APK's
environment: on 2026-11-16 these lines ran at import, the agent-comms installer imported every
Toad module to check them, and from then on its worker's HOME was this folder's `home`, so the
install published its runtime there and rolled back.
"""

import os
from pathlib import Path

APP = Path(__file__).resolve().parents[2]


def enter() -> None:
    """Make this process the APK's: its settings, state and home live in the app folder."""
    for speedup in ("AIOHTTP", "MULTIDICT", "YARL", "FROZENLIST", "PROPCACHE"):
        os.environ[f"{speedup}_NO_EXTENSIONS"] = "1"
    os.environ["SSL_CERT_FILE"] = str(APP / "cacert.pem")
    os.environ["PYWAL_CACHE_DIR"] = str(APP / "wal")
    os.environ["XDG_STATE_HOME"] = str(APP / "state")
    os.environ["HOME"] = str(APP / "home")
