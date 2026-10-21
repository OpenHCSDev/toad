"""Enter in the editor while a native turn runs queues the input; leaving and returning by tab click keeps the editor."""

from agent_comms.pi_vocabulary import HighThinkingLevel

from support.native import native_session
from toad.navigation_target import NavigationContext, channel_target
from toad.widgets.comms_menu import ContextMenu
from toad.widgets.prompt import AgentInfo, QueueSummary
from toad.widgets.transcript_history import TranscriptHistory


async def test_enter_queues_during_a_turn_and_a_tab_click_returns_to_the_same_editor(workspace, native_package):
    async with native_session(workspace) as native:
        ui, agent, comms, provider = native.ui, native.agent, native.comms, native.provider
        app, pilot = ui.textual
        view = ui.conversation
        owner_tab = ui.selected_tab
        await ui.until_agent_ready()
        provider.hold_next_request()
        await ui.write_draft("NATIVE_EDITOR_FIRST")
        await ui.press("enter")
        await ui.until(provider.entered.is_set, seconds=30, why="the first input at the provider")
        await ui.until(lambda: native.executing, seconds=20, why="the running turn")

        await ui.write_draft("NATIVE_EDITOR_QUEUED")
        await ui.press("enter")
        await ui.until(lambda: bool(view.submissions.queue_projection.items), seconds=20, why="the queued input")
        assert "NATIVE_EDITOR_QUEUED" in view.query_one(QueueSummary).render().plain
        provider.release()
        await ui.until(lambda: len(provider.requests) == 2 and not native.executing, seconds=35,
                       why="both turns to finish")
        await ui.until(lambda: "NATIVE_RESPONSE_2" in ui.painted(view.window), seconds=25, why="the second answer")
        await ui.until(lambda: not view.submissions.queue_projection.items and view.turns.managed_id is None,
                       seconds=20, why="an empty queue and no turn")
        assert ui.agent_ready()
        await ui.until(lambda: all(history.checkpoint_available
                                   for history in view.contents.query(TranscriptHistory)), seconds=20,
                       why="saved history to be available")
        view.window.anchor()
        view.transcript.require_checkpoint()
        await ui.until(lambda: not view.transcript.dirty and "NATIVE_RESPONSE_2" in ui.painted(view.window),
                       seconds=20, why="the answer from saved history")
        assert view.contents.query(TranscriptHistory)
        assert view.transcript.displayed_cursor is not None

        await ui.write_draft("PRESERVED_UNSENT_DRAFT")
        editor = view.prompt.prompt_text_area
        document, undo = editor.document, editor.history
        owner = comms.registry.require("beta").process_identity
        assert await pilot.click(view.prompt.query_one(AgentInfo))
        await ui.until(lambda: view.prompt.model_switcher.search_input.has_focus, why="the model picker")
        await ui.press("down", "enter")
        await ui.until(lambda: isinstance(app.screen, ContextMenu), why="the thinking menu")
        high = next(item for item in app.screen.query("ContextMenuItem") if item.action == "high")
        await ui.until(lambda: high in app.screen._compositor.visible_widgets and high.region.width > 0,
                       why="the 'high' menu item")
        assert await pilot.click(high, offset=(1, 0))
        await ui.until(lambda: agent.configuration.thinking.current == "high", seconds=20, why="the thinking level")
        assert comms.registry.require("beta").thinking_level is HighThinkingLevel

        user = comms.messaging.user_identity(str(native.project)).name
        await channel_target("#team").open(NavigationContext(app, owner_tab, native.project, user))
        await app.selected_session.wait_content_ready()
        assert ui.selected_tab != owner_tab
        assert await pilot.click(f"SessionLabel#{owner_tab}")
        await ui.until(lambda: ui.selected_tab == owner_tab and "NATIVE_RESPONSE_2" in ui.painted(view.window),
                       seconds=20, why="the session after clicking its tab")
        assert ui.conversation is view
        assert ui.draft() == "PRESERVED_UNSENT_DRAFT"
        assert editor.document is document and editor.history is undo
        assert comms.registry.require("beta").process_identity == owner
        assert len(provider.requests) == 2
        await agent.session.reconnect()
        await ui.until(agent.session.settled.is_set, seconds=30, why="the reconnect to settle")
        await ui.until(lambda: ui.agent_ready() and "NATIVE_RESPONSE_2" in ui.painted(view.window), seconds=20,
                       why="history after reattaching")
        assert agent.configuration.thinking.current == "high"
        assert len(provider.requests) == 2 and not view.submissions.queue_projection.items
