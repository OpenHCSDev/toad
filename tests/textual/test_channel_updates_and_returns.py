"""A real shared observer updates a shown channel and leaves its parked view alone."""

import asyncio

async def test_live_update_paints_parked_channel_reads_nothing_and_return_shows_the_update(workspace):
    from toad.widgets.comms_chat import CommsChatView, session_thread_name

    comms = workspace.comms
    for name in ("sender", "reader", session_thread_name(workspace.project)):
        workspace.thread(name, "alpha")
    initial = comms.messaging.send("sender", "#alpha", "INITIAL ROW").message
    async with workspace.app(size=(113, 34)) as ui:
        app = ui.textual[0]
        access = app.coordination_access
        owner = ui.selected_tab
        mode = await ui.open_channel("#alpha", actor="reader")
        chat = app.selected_session.query_one(CommsChatView)
        await ui.until_shows("INITIAL ROW")
        await chat.message_history.toggle_style()
        await ui.until(
            lambda: any(initial.reference in read.references for read in access.notification_interest.reads),
            why="the shown channel to subscribe to its notification references",
        )

        comms.messaging.send("sender", "#alpha", "LIVE UPDATE")
        await ui.until_shows("LIVE UPDATE")

        await ui.select_tab(owner)
        await ui.until(lambda: not access.notification_interest.reads, why="the parked channel to unsubscribe")
        comms.messaging.send("sender", "#alpha", "PARKED UPDATE")
        await ui.step(1.2)
        assert not access.notification_views and not access.notification_interest.reads
        await ui.select_tab(mode)
        await ui.until_shows("PARKED UPDATE")
        await ui.until(lambda: bool(access.notification_interest.reads), why="the returned channel to resubscribe")
        assert app.selected_session.query_one(CommsChatView) is chat


async def test_first_wire_page_paints_before_pending_sidebar_and_keeps_source_fences(workspace):
    from agent_comms.launch_root import LaunchRoot
    from support.roots import installed_wire
    from toad.preferences import SETTINGS
    from toad.widgets.channel_prompt import ChannelPrompt
    from toad.widgets.comms_chat import CommsChatView

    sender = workspace.thread("sender", "first-page")
    workspace.thread("reader", "first-page")
    workspace.comms.messaging.send("sender", "#first-page", "FIRST_PAGE_WITHOUT_SIDEBAR")
    other = installed_wire(workspace.roots.attempt / "other-route")
    async with workspace.app(size=(113, 34)) as ui:
        app = ui.app
        access = app.coordination_access
        await access.current_sidebar()
        observed = access.observation.observed()
        process = observed.process
        # Join the actual receiver, not a replacement service or fake answer.
        # Its child keeps running and the real sidebar reply remains in its pipe.
        await process._reader.aclose()
        async with asyncio.timeout(20), asyncio.TaskGroup() as work:
            try:
                app.saved_settings.toggle(SETTINGS.sidebar.show_archived)
                sidebar = work.create_task(access.current_sidebar())
                references = work.create_task(
                    observed.current_references(access, str(workspace.comms.root)),
                )
                await ui.until(lambda: bool(access.sidebar_waiters),
                               why="the genuine changed-interest sidebar answer to remain pending")
                opening = work.create_task(ui.open_channel("#first-page", actor="reader"))
                await ui.until_shows("FIRST_PAGE_WITHOUT_SIDEBAR")
                chat = app.selected_session.query_one(CommsChatView)
                history = chat.message_history
                source = history.page_source
                assert not history.undrawn
                assert not sidebar.done() and not references.done()
                assert not chat.query_one(ChannelPrompt)._candidates
            finally:
                # Reattach the same observer's one reader; deliver its original reply.
                process.start_receiving(observed.receive, observed.receive_failed)
            mode = await opening
            answer = await sidebar
            catalog = await references
        assert catalog.thread(sender.incarnation).name == sender.name
        assert answer.require_snapshot().references.thread(sender.incarnation).name == sender.name
        await ui.until(
            lambda: any(candidate.name == sender.name
                        for candidate in chat.query_one(ChannelPrompt)._candidates),
            why="the genuine channel mention label to finish after its sidebar answer",
        )
        assert chat.agent_info.plain == chat.conversation.label(catalog)
        snapshot = history.source_snapshot()
        source = history.page_source
        with LaunchRoot.from_path(other.root).selected():
            assert not await history.source_is_current(snapshot)
        assert await history.source_is_current(snapshot)
        await app.session_navigation.close(mode)
        assert source.closed
        assert not await source.route_is_current()
