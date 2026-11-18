"""Run as its own interpreter: keymap discovery catalogues the keys of a view nothing in it
has opened, once the frontend has imported its views.

tests/textual/test_keymap_discovery.py starts it with `python -m`, because the app test
template imports every toad module before it forks a test.
"""

import sys

from toad.key_modes import KeyMode, Standard
from toad.keymap import KeymapCatalog, KeymapRow

assert "toad.widgets.channels_sidebar" not in sys.modules
# The frontend imports the views it keys before reading the keymap (`KeymapCatalog.capture`):
# the comms sidebar's keys while it holds the window are catalogued though nothing opened it.
import toad.app  # noqa: E402,F401
from toad.widgets.channels_sidebar import SoleNewSessionAction  # noqa: E402
catalog = KeymapCatalog.capture(tuple(KeyMode.members_with(KeyMode)))

row = KeymapRow.of(SoleNewSessionAction(), Standard)
assert catalog.require(row.declaration).key_title() == SoleNewSessionAction().key_title()
assert catalog.defaults(row) == SoleNewSessionAction.keys[Standard.binding_mode()]
