"""Textual-facing: a session whose mount fails leaves the workspace, instead of crashing later as a missing sidebar."""

from agent_comms.repo import Checkout
import pytest

from support.ui import saved_tab

from toad.screens.main import MainScreen
from toad.workspace_sessions import SessionStartFailed


class FailsToStart(MainScreen):
    def on_mount(self) -> None:
        raise ValueError("START_FAILURE")


async def test_a_failed_mount_names_the_session_and_leaves_no_dead_view(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        before = set(app.workspace_sessions.views)
        with pytest.raises(SessionStartFailed):
            await app.session_navigation.new(
                await saved_tab(app), lambda: FailsToStart(Checkout(workspace.project)))
        assert set(app.workspace_sessions.views) == before
