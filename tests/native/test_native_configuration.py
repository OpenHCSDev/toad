"""Changing the thinking level from the picker while a native turn runs: applied at once, kept after reattaching."""

from agent_comms.pi_vocabulary import HighThinkingLevel

from support.native import native_session
from toad.core import input_events
from toad.widgets.comms_menu import ContextMenu
from toad.widgets.prompt import AgentInfo


async def test_thinking_level_changes_during_a_turn_and_survives_reattaching(workspace, native_package):
    async with native_session(workspace, native_package) as native:
        ui, agent, comms, provider = native.ui, native.agent, native.comms, native.provider
        app, pilot = ui.textual
        view = ui.conversation
        await ui.until_agent_ready()
        provider.hold_next_request()
        await view.submit_input(input_events.UserInputSubmitted("CONFIGURATION_SAVED_HISTORY"))
        await ui.until(provider.entered.is_set, seconds=30, why="the input at the provider")
        assert native.executing
        await ui.write_draft("CONFIGURATION_UNSENT_DRAFT")
        document = view.prompt.prompt_text_area.document
        undo = view.prompt.prompt_text_area.history
        assert await pilot.click(view.prompt.query_one(AgentInfo))
        picker = view.prompt.model_switcher
        await ui.until(lambda: picker.search_input.has_focus, why="the model picker")
        await ui.press("down", "enter")
        await ui.until(lambda: isinstance(app.screen, ContextMenu), why="the thinking menu")

        def high():
            return next((item for item in app.screen.query("ContextMenuItem") if item.action == "high"), None)

        await ui.until(lambda: high() is not None and high() in app.screen._compositor.visible_widgets
                       and high().region.width > 0, why="the 'high' menu item")
        assert await pilot.click(high(), offset=(1, 0))
        await ui.until(lambda: comms.registry.require("beta").thinking_level is HighThinkingLevel,
                       seconds=15, why="the thinking level on the owner")
        await ui.until(lambda: agent.configuration.thinking.current == "high", seconds=15,
                       why="the thinking level in the agent's configuration")
        assert native.executing, "The picker waited for the turn to finish"
        assert not provider.released.is_set(), "The picker released the held model reply"
        provider.release()
        await ui.until(lambda: "NATIVE_RESPONSE_1" in ui.painted(view.window), seconds=30, why="the answer")
        await ui.until(lambda: not native.executing, seconds=20, why="the turn to finish")
        await agent.session.reconnect()
        await ui.until(agent.session.settled.is_set, seconds=30, why="the reconnect to settle")
        await ui.until(lambda: agent.configuration.thinking.current == "high" and ui.agent_ready(), seconds=20,
                       why="the thinking level after reattaching")
        await ui.until(lambda: "NATIVE_RESPONSE_1" in ui.painted(view.window), seconds=20, why="history after reattaching")
        assert ui.draft() == "CONFIGURATION_UNSENT_DRAFT"
        assert view.prompt.prompt_text_area.document is document
        assert view.prompt.prompt_text_area.history is undo
        assert len(provider.requests) == 1
        await ui.until(lambda: "high" in view.agent_info.plain, why="the level beside the model name")
        assert ui.shows("NATIVE_RESPONSE_1") and ui.shows("CONFIGURATION_UNSENT_DRAFT")
