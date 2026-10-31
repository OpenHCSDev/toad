"""Queue details keep their original project while mounted as a separate screen."""

from textual.widgets import Button

from toad.project_path_owner import ProjectPathOwner
from toad.screens.queue import QueueInspection
from toad.widgets.tool_content import ToolContent


async def test_queue_details_mount_with_the_original_project_and_keep_the_draft(workspace):
    async with workspace.app(size=(115, 38)) as ui:
        view = ui.conversation
        owner = ProjectPathOwner.containing(view)
        view.prompt.text = "Keep this unsent queue draft"
        view.open_queue_menu()
        await ui.until(lambda: isinstance(ui.app.screen, QueueInspection), why="the queue inspection screen")
        screen = ui.app.screen
        await ui.until(lambda: bool(screen.query(ToolContent)), why="the mounted rich queue details")
        details = screen.query_one(ToolContent)
        assert ProjectPathOwner.containing(details) is screen
        assert screen.source_view is view
        assert screen.project_root == owner.project_root
        assert screen.coordination_root == owner.coordination_root
        assert screen.link_context_events is owner.link_context_events
        assert screen.query_one("#queue-send-now", Button).disabled
        await ui.press("escape")
        await ui.until(lambda: ui.app.screen is not screen, why="the dismissed queue inspection")
        assert view.prompt.text == "Keep this unsent queue draft"
