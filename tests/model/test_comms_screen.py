"""The comms screen owns a composition tree that does not require ambient app state."""

from pathlib import Path

from textual import containers

from toad.conversation_kind import ChannelConversation
from toad.screens.comms import CommsScreen


def test_unmounted_comms_screen_declares_its_shell_without_an_active_app():
    screen = CommsScreen(
        project_path=Path("/project"),
        owner_mode="owner",
        me="viewer",
        target="#channel",
        kind=ChannelConversation,
    )

    result = tuple(screen.compose())

    assert len(result) == 1
    assert isinstance(result[0], containers.Center)
