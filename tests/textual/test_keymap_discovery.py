"""Discovery includes screens that the current application has not opened."""

import sys

from toad.key_modes import KeyMode, Standard
from toad.keymap import KeymapCatalog, KeymapRow


def test_unopened_screen_invocations_are_discovered_in_a_fresh_process(workspace):
    # `workspace` gives this case its own interpreter, independent of other imports.
    assert "toad.screens.welcome" not in sys.modules
    catalog = KeymapCatalog.capture(tuple(KeyMode.members_with(KeyMode)))
    assert "toad.screens.welcome" in sys.modules
    from toad.screens.welcome import NewSessionAction

    row = KeymapRow.of(NewSessionAction(), Standard)
    assert catalog.require(row.declaration).key_title() == NewSessionAction().key_title()
    assert catalog.defaults(row) == NewSessionAction.keys[Standard().binding_mode]
