"""Closing a real pipe with queued native events cancels the observer process cleanly."""

import subprocess
import sys

import support.watchers


def test_closing_the_pipe_with_unread_native_events_ends_the_observer_without_errors(tmp_path):
    result = subprocess.run([sys.executable, support.watchers.__file__, "--peer-close", str(tmp_path)],
                            capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stderr
    assert not result.stderr, result.stderr
