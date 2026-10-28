"""Discovery includes screens that the current application has not opened."""

import sys

from toad.key_modes import KeyMode, Standard
from toad.keymap import KeymapCatalog, KeymapRow


def test_unopened_screen_invocations_are_discovered_in_a_fresh_process(workspace):
    # `workspace` gives this case its own interpreter, independent of other imports.
    assert "toad.screens.store" not in sys.modules
    catalog = KeymapCatalog.capture(tuple(KeyMode.members_with(KeyMode)))
    assert "toad.screens.store" in sys.modules
    from toad.screens.store import LaunchSlotAction

    for slot, key in enumerate(LaunchSlotAction.keys[Standard().binding_mode]):
        row = KeymapRow.of(LaunchSlotAction(slot), Standard)
        assert catalog.require(row.declaration).key_title() == LaunchSlotAction(slot).key_title()
        assert catalog.defaults(row) == (key,)
