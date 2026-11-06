"""The failure that ended the app is saved even when closing the app raised a second error or was interrupted."""

import pytest

from toad.cli import run_terminal
from toad.paths import get_errors


class EndedApp:
    """An app whose UI failed with `retained` and whose run then ends with `closing`."""

    return_code = 1

    def __init__(self, retained, closing=None):
        self._exception = retained
        self.closing = closing

    def run(self):
        if self.closing is not None:
            raise self.closing


def saved():
    return sorted(path.read_text() for path in get_errors().glob("Terminal_crash*.txt"))


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Saved failures land under this test's own state directory."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))


def test_a_closing_error_does_not_replace_the_failure_that_ended_the_app():
    with pytest.raises(RuntimeError, match="CLOSING_FAILED"):
        run_terminal(EndedApp(ValueError("UI_FAILED"), RuntimeError("CLOSING_FAILED")))
    closing, ui = saved()
    assert "RuntimeError: CLOSING_FAILED" in closing and "ValueError: UI_FAILED" in ui


def test_an_interrupted_close_still_saves_the_failure_that_ended_the_app():
    with pytest.raises(KeyboardInterrupt):
        run_terminal(EndedApp(ValueError("UI_FAILED"), KeyboardInterrupt()))
    (ui,) = saved()
    assert "ValueError: UI_FAILED" in ui


def test_a_ui_failure_alone_is_saved_once_and_exits_with_the_app_status():
    with pytest.raises(SystemExit) as exit:
        run_terminal(EndedApp(ValueError("UI_FAILED")))
    assert exit.value.code == 1
    (ui,) = saved()
    assert "ValueError: UI_FAILED" in ui
