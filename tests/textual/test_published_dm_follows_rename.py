"""The published visible target of a DM view follows a real peer rename.

The selected view is published; its target is derived live from it. After the registry
rename, the view's own target and the published target must both name the peer's new name.
"""

import asyncio

from toad.navigation_context import NavigationContext
from toad.navigation_target import DirectTarget


async def test_the_published_dm_target_follows_a_real_peer_rename(workspace):
    workspace.thread("peer", "team")
    viewer = workspace.viewer
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        context = NavigationContext(app, ui.selected_tab, app.project_dir, viewer)
        await DirectTarget("peer").open(context)
        screen = app.selected_session
        await screen.wait_content_ready()
        root = screen.thread_identity.root_path
        sessions = app.workspace_sessions

        def published_name():
            target = sessions.visible_target(root)
            return getattr(target, "name", None)

        assert published_name() == "peer"
        workspace.comms.registry.rename("peer", "renamed-peer")
        for _ in range(60):
            await asyncio.sleep(0.1)
            if published_name() == "renamed-peer":
                break
        assert screen.navigation_target.name == "renamed-peer"
        assert published_name() == "renamed-peer", "the published DM target must follow the rename"
