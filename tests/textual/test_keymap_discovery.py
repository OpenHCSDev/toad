"""Discovery includes screens that the current application has not opened."""

from pathlib import Path
import subprocess
import sys

TESTS = Path(__file__).resolve().parents[1]


def test_unopened_screen_invocations_are_discovered_in_a_fresh_process(workspace):
    # The app test template imports every toad module before it forks, so only a new
    # interpreter starts without the welcome screen; `workspace` gives it this case's roots.
    run = subprocess.run([sys.executable, "-m", "support.keymap_discovery"],
                         cwd=TESTS, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
