"""A channel tab saved at exit is restored on the next start, and the workspace draws."""

from toad.screens.workspace import WorkspaceScreen


async def test_saved_channel_tab_restores_and_draws_on_next_start(workspace):
    workspace.thread("owner")
    async with workspace.app(size=(140, 32)) as ui:
        channel = await ui.open_channel("#all", actor="owner")
    async with workspace.app(size=(140, 32), session=False) as ui:
        app, _ = ui.textual
        assert channel in [tab.identity for tab in ui.tabs()]
        assert isinstance(app.screen, WorkspaceScreen)
        await app.selected_session.wait_content_ready()
