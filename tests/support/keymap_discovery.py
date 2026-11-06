"""Run as its own interpreter: keymap discovery imports a screen nothing in it has opened.

tests/textual/test_keymap_discovery.py starts it with `python -m`, because the app test
template imports every toad module before it forks a test.
"""

import sys

from toad.key_modes import KeyMode, Standard
from toad.keymap import KeymapCatalog, KeymapRow

assert "toad.screens.welcome" not in sys.modules
catalog = KeymapCatalog.capture(tuple(KeyMode.members_with(KeyMode)))
assert "toad.screens.welcome" in sys.modules
from toad.screens.welcome import NewSessionAction  # noqa: E402 - discovery imported it

row = KeymapRow.of(NewSessionAction(), Standard)
assert catalog.require(row.declaration).key_title() == NewSessionAction().key_title()
assert catalog.defaults(row) == NewSessionAction.keys[Standard.binding_mode()]
