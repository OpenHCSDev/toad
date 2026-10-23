"""Textual-facing: while a route's metadata is read off the UI thread the prompt keeps taking keys, focus stays where the user moved it, and a superseded or orphaned opening creates no tab."""












async def test_a_renamed_thread_reuses_its_open_tab_before_the_rename_reaches_the_view(
    workspace,
):
    workspace.thread("metadata-peer", running=True)
    async with workspace.app(size=(100, 32)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        other = await ui.new_session()
        existing = app.session_navigation.source(other)
        existing.initial_coordination_root = str(workspace.roots.wire)
        existing._comms_thread = "metadata-peer"
        workspace.comms.registry.rename("metadata-peer", "metadata-renamed")
        reused = await app.thread_navigation.open(
            owner_mode=owner, project_path=workspace.project, target="metadata-peer"
        )
        assert reused == other and app.session_tracker.session_count == 2
