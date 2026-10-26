"""Reconnecting to a native owner shows each saved answer exactly once, even when two answers have the same text."""

from agent_comms.transcript_events import AssistantTranscript, UserTranscript

from support.native import ControlledProvider, native_session

BODY = "EQUAL_NATIVE_REPLY"


async def test_equal_answers_are_each_drawn_once_before_and_after_reconnect(workspace, native_package):
    provider = ControlledProvider(reply=lambda request, number: ({"role": "assistant", "content": BODY}, "stop"),
                                  request_budget=2)
    async with native_session(workspace, provider=provider) as native:
        ui, agent, comms = native.ui, native.agent, native.comms
        view = ui.conversation
        await ui.until_agent_ready()
        owner = comms.registry.require("beta").process_identity

        async def shows_exactly(expected):
            await ui.until(lambda: BODY in ui.painted(view.window), seconds=30, why="the answer")
            page = await agent.get_transcript_page()
            await ui.until(lambda: not view.window.history_lock.locked() and any(
                history.page_source.through == page.after for history in view.window.histories
                if history.is_attached and history.state.reports_coverage), seconds=20,
                why="saved history up to the end of the session file")
            await ui.until(lambda: ui.painted(view.window).count(BODY) == expected, seconds=10,
                           why=f"{expected} drawn answer(s)")
            answers = [event for event in page.events if isinstance(event, AssistantTranscript)]
            inputs = [event for event in page.events if isinstance(event, UserTranscript)]
            assert len(answers) == expected and all(event.text == BODY for event in answers)
            assert len(inputs) == expected and len({event.native_id for event in inputs}) == expected
            assert ui.painted(view.window).count("Agent ·") == expected
            assert comms.registry.require("beta").process_identity == owner
            assert len(provider.requests) == expected

        for number in (1, 2):
            await ui.write_draft(f"DISTINCT_INPUT_{number}")
            await ui.press("enter")
            await ui.until(lambda: len(provider.requests) == number, seconds=30, why="the input at the provider")
            await ui.until(lambda: not native.executing, seconds=20, why="the turn to finish")
            await shows_exactly(number)
            await agent.session.reconnect()
            await ui.until(agent.session.settled.is_set, seconds=30, why="the reconnect to settle")
            await ui.until_agent_ready()
            await shows_exactly(number)


async def test_returning_during_a_turn_loads_messages_written_while_hidden(workspace, native_package):
    import json
    import threading

    hidden_ready, return_ready = threading.Event(), threading.Event()
    release_hidden, release_return = threading.Event(), threading.Event()

    def reply(request, number):
        if number == 2:
            hidden_ready.set()
            assert release_hidden.wait(25), "test never hid the tab"
        if number == 3:
            return_ready.set()
            assert release_return.wait(25), "test never returned to the tab"
            return {"role": "assistant", "content": "AFTER_TAB_RETURN"}, "stop"
        label = "BEFORE_TAB_PARK" if number == 1 else "WHILE_TAB_HIDDEN"
        return {"role": "assistant", "content": label, "tool_calls": [{
            "id": f"call_{number}", "type": "function", "function": {
                "name": "bash", "arguments": json.dumps({"command": f"printf '{label}_TOOL'"})}}]}, "tool_calls"

    provider = ControlledProvider(reply=reply, request_budget=3)
    try:
        async with native_session(workspace, provider=provider, size=(160, 55)) as native:
            ui = native.ui
            view, tab = ui.conversation, ui.selected_tab
            await ui.until_agent_ready()
            await ui.write_draft("EXERCISE_BACKGROUND_HISTORY")
            await ui.press("enter")
            await ui.until(hidden_ready.is_set, seconds=30, why="the first tool to finish")
            await ui.until_shows("BEFORE_TAB_PARK")
            await ui.new_session()
            release_hidden.set()
            await ui.until(return_ready.is_set, seconds=30, why="the hidden tool to finish")
            await ui.select_tab(tab)
            assert ui.conversation is view
            assert native.executing
            await ui.until_shows("WHILE_TAB_HIDDEN")
            release_return.set()
            await ui.until_shows("AFTER_TAB_RETURN", seconds=30)
            await ui.until(lambda: not native.executing, seconds=20, why="the turn to finish")
    finally:
        release_hidden.set()
        release_return.set()
