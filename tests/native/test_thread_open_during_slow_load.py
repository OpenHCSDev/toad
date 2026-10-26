"""Opening a thread whose session loads slowly: one tab from the first click, the loading state,
then the saved history; the session left behind keeps its editor."""
from agent_comms.repo import Checkout
from toad.session_scope import AgentAttached

import asyncio
from functools import partial

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
import os

from support.agents import peer
from support.native import start_private_native_wire
from support.stylesheets import INSTALLED
from support.textual_steps import channel_roster
from toad.app import ToadApp
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.widgets.comms_sidebar import ChannelGroup
from toad.widgets.conversation import ThreadLoading


class TabFramesApp(ToadApp):
    CSS_PATH = INSTALLED

    def __init__(self, **arguments):
        self.tab_sets_drawn = []
        super().__init__(**arguments)

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if renderable is not None and not self._batch_count:
            self.tab_sets_drawn.append(tuple(tab.mode_name for tab in self.open_tabs))


async def test_a_slow_thread_open_uses_one_tab_and_ends_with_saved_history(workspace, native_package):
    project = workspace.project
    comms = start_private_native_wire(workspace.roots.wire)
    for name in ("owner", "fresh-peer"):
        comms.registry.declare(Thread(name, frozenset({"journey"}), Checkout(project),
                                      process_identity=ProcessIdentity.capture(os.getpid())))
    comms.channels.create_tag("journey")
    comms.messaging.send("owner", "#journey", "SAVED_CHANNEL_JOURNEY")
    started = partial(TabFramesApp, agent_session_id="owner")
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

        open_peer = partial(app.thread_navigation.open, owner_mode=owner, project_path=project, target="fresh-peer")
        assert await pilot.click(group.members["fresh-peer"])
        opening = asyncio.create_task(open_peer())
        duplicate = asyncio.create_task(open_peer())
        try:
            await ui.until(lambda: (project / "load-entered-fresh-peer").exists(), seconds=12,
                           why="the agent to begin loading the thread")
            tab = ui.selected_tab
            assert tab != owner
            view = app.selected_session
            agent = view.conversation.agent_binding
            await ui.until(lambda: bool(view.query(ThreadLoading)), why="the loading block")
            await ui.until_shows(ThreadLoading.LABEL)
            assert tuple(app.tab_order.names) == (*tabs_before, app.session_navigation.get(tab).identity)
            details = app.session_navigation.session_details(tab)
            assert details.name.display == "fresh-peer"

            workspace.release("load-fresh-peer")
            assert await opening == tab and await duplicate == tab
            await ui.until(lambda: view.conversation.agent_ready, seconds=12, why="the opened thread to be ready")
            await ui.until_shows("SAVED_FIRST_OPEN_fresh-peer")
            assert app.selected_session is view and view.conversation.agent_binding is agent
            assert app.session_navigation.session_details(tab) is details
            await ui.until(lambda: not view.query(ThreadLoading), why="the loading block to go")
            # This peer has no Core input queue. The real-owner first-message case is
            # test_native_journey.py::test_a_second_thread_opened_from_the_app_answers_its_first_message.
            assert tuple(app.tab_order.names) == (*tabs_before, app.session_navigation.get(tab).identity)
            assert all(len(drawn) <= 3 and not any(name.startswith("pending-") for name in drawn)
                       for drawn in app.tab_sets_drawn)
        finally:
            opening.cancel()
            duplicate.cancel()
            await asyncio.gather(opening, duplicate, return_exceptions=True)
