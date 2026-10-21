"""Opening a thread whose session loads slowly: one tab from the first click, the loading state,
then the saved history; the session left behind keeps its editor."""
from toad.session_scope import AgentAttached

import asyncio
from functools import partial
from threading import Event
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
import os

from support.agents import peer
from support.native import start_private_native_wire
from support.textual_steps import channel_roster
from toad.app import ToadApp
from toad.navigation_preparation import ThreadNavigationRequest
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.widgets.comms_sidebar import ChannelGroup
from toad.widgets.conversation import ThreadLoading


async def test_a_slow_thread_open_uses_one_tab_and_ends_with_saved_history(workspace, native_package):
    project = workspace.project
    comms = start_private_native_wire(workspace.roots.wire)
    for name in ("owner", "fresh-peer"):
        comms.registry.declare(comms.registry.new_thread(name, frozenset({"journey"}), str(project),
                                      process_identity=ProcessIdentity.capture(os.getpid())))
    comms.channels.create_tag("journey")
    comms.messaging.send_initial_cohort("owner", "#journey", "SAVED_CHANNEL_JOURNEY")
    tab_sets_drawn = []

    def started(**arguments):
        app = ToadApp(agent_session_id="owner", **arguments)
        draw = app._display

        def recording_draw(screen, renderable):
            draw(screen, renderable)
            if renderable is not None and not app._batch_count:
                tab_sets_drawn.append(tuple(tab.mode_name for tab in app.open_tabs))

        app._display = recording_draw
        return app

    async with workspace.app(size=(139, 25), binding=AgentAttached(peer("delayed_load")), application=started) as ui:
        app, pilot = ui.textual
        await ui.until_agent_ready()
        source = app.selected_session
        owner = ui.selected_tab
        await ui.write_draft("RETAINED_DRAFT")
        editor = source.conversation.prompt.prompt_text_area
        document, undo = editor.document, editor.history

        def journey_group(roster):
            return next(group for group in roster.query(ChannelGroup) if group.row.target_name == "#journey")

        app.screen.query_one(ChannelsSidebar).reveal()
        roster = await channel_roster(ui, "#journey")
        await ui.step()
        assert await pilot.click(journey_group(roster).row)
        await ui.until(lambda: ui.selected_tab != owner, why="the channel tab")
        channel = ui.selected_tab
        await app.selected_session.wait_content_ready()
        await ui.until_shows("SAVED_CHANNEL_JOURNEY")
        await ui.select_tab(owner)
        await ui.until_agent_ready()
        assert ui.draft() == "RETAINED_DRAFT"
        assert editor.document is document and editor.history is undo
        await ui.select_tab(channel)
        await ui.until_shows("SAVED_CHANNEL_JOURNEY")
        roster = await channel_roster(ui, "#journey")
        group = journey_group(roster)
        group.toggle_members()
        await ui.until(lambda: "fresh-peer" in group.members, why="the channel's members")
        tabs_before = tuple(app.tab_order.names)

        entered, release = Event(), Event()
        read = ThreadNavigationRequest.read

        def held_read(request):
            entered.set()
            assert release.wait(10)
            return read(request)

        open_peer = partial(app.thread_navigation.open, owner_mode=owner, project_path=project, target="fresh-peer")
        with patch.object(ThreadNavigationRequest, "read", held_read):
            assert await pilot.click(group.members["fresh-peer"])
            opening = asyncio.create_task(open_peer())
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                duplicate = asyncio.create_task(open_peer())
                await ui.step()
                assert tuple(app.tab_order.names) == tabs_before
                assert len(app.thread_navigation.pending) == 1 and not duplicate.done()
                release.set()
                await ui.until(lambda: (project / "load-entered-fresh-peer").exists(), seconds=12,
                               why="the agent to begin loading the thread")
                tab = ui.selected_tab
                assert tab != owner
                view = app.selected_session
                agent = view.conversation.agent
                await ui.until(lambda: bool(view.query(ThreadLoading)), why="the loading block")
                await ui.until_shows(ThreadLoading.LABEL)
                assert tuple(app.tab_order.names) == (*tabs_before, tab)
                details = app.session_tracker.get_session(tab)

                assert details.name.display == "fresh-peer"
                workspace.release("load-fresh-peer")
                assert await opening == tab and await duplicate == tab
                await ui.until(lambda: view.conversation.agent_ready, seconds=12, why="the opened thread to be ready")
                await ui.until_shows("SAVED_FIRST_OPEN_fresh-peer")
                assert app.selected_session is view and view.conversation.agent is agent
                assert app.session_tracker.get_session(tab) is details
                await ui.until(lambda: not view.query(ThreadLoading), why="the loading block to go")
                # No message is sent here: this scripted agent claims a Core thread but publishes no input
                # queue, and Toad accepts input for a Core thread only once its owner's queue is known.
                # The first message after opening a thread is sent to a real owner in
                # test_native_journey.py::test_a_second_thread_opened_from_the_app_answers_its_first_message.
                assert tuple(app.tab_order.names) == (*tabs_before, tab)
                assert all(len(drawn) <= 3 and not any(name.startswith("pending-") for name in drawn)
                           for drawn in tab_sets_drawn)
            finally:
                release.set()
