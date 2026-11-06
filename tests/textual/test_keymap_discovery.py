"""Discovery includes screens that the current application has not opened."""

from pathlib import Path
import subprocess
import sys

import toad

DISCOVERY = """
import sys

from toad.key_modes import KeyMode, Standard
from toad.keymap import KeymapCatalog, KeymapRow

assert "toad.screens.welcome" not in sys.modules
catalog = KeymapCatalog.capture(tuple(KeyMode.members_with(KeyMode)))
assert "toad.screens.welcome" in sys.modules
from toad.screens.welcome import NewSessionAction

row = KeymapRow.of(NewSessionAction(), Standard)
assert catalog.require(row.declaration).key_title() == NewSessionAction().key_title()
assert catalog.defaults(row) == NewSessionAction.keys[Standard.binding_mode()]
"""


def test_unopened_screen_invocations_are_discovered_in_a_fresh_process(workspace):
    # The app test template imports every toad module before it forks, so only a new
    # interpreter starts without the welcome screen; `workspace` gives it this case's roots.
    source = str(Path(toad.__file__).parents[1])
    run = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {source!r})\n{DISCOVERY}"],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
