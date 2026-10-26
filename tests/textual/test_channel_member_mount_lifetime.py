"""A real sidebar can hide between stepped member mounting frames."""


from toad.widgets.comms_sidebar import CommsSidebar


async def test_pending_channel_members_stop_when_sidebar_hides_and_resume_when_shown(workspace):
    for index in range(12):
        workspace.thread(f'frame-peer-{index}', 'frames')
    async with workspace.app() as ui:
        app, _ = ui.textual
        sidebar = app.workspace_chrome.channels
        sidebar.reveal()
        tree = sidebar.query_one(CommsSidebar)
        await ui.until(lambda: '#frames' in tree.groups and tree.groups['#frames'].is_mounted,
                       why='the mounted channel header')
        group = tree.groups['#frames']
        assert not group.expanded and not group.rows
        screen = group.screen
        budget = screen.LAYOUT_STEP_NS
        try:
            # Exhaust one real layout budget so expansion leaves native row work
            # for the next frame; do not fabricate a model or a worker result.
            screen.LAYOUT_STEP_NS = 0
            group.toggle_members()
            await ui.until(lambda: group._row_mounting is not None
                           and group._row_mounting.is_running,
                           why='member mounting waiting for its next frame')
            worker = group._row_mounting
            sidebar.collapsed = True
            assert not tree.model_state.shows_model()
        finally:
            screen.LAYOUT_STEP_NS = budget
        await ui.until(lambda: worker.is_finished, why='hidden member work to finish')
        assert worker.error is None
        assert not group.rows
        sidebar.reveal()
        await ui.until(lambda: len(group.rows) == 12, why='all members after revealing the sidebar')
        assert set(group.rows) == {f'frame-peer-{index}' for index in range(12)}
        assert all(row.is_mounted for row in group.rows.values())
