"""A permission question asked while its tab is hidden is there on return and its answer reaches the agent."""

from support.agents import peer, script


def answers(workspace):
    return [fact["answered"] for fact in workspace.received() if "answered" in fact]


async def test_permission_asked_in_the_shown_tab_is_answered(workspace):
    async with workspace.app(size=(110, 40), agent=peer("scripted")) as ui:
        await ui.until_agent_ready()
        await ui.write_draft(script({"ask": "PERMISSION_FOR_EDIT"}))
        await ui.press("enter")
        await ui.until_shows("PERMISSION_FOR_EDIT")
        await ui.until_shows("a Allow")
        await ui.press("a")
        await ui.until(lambda: answers(workspace) == ["Allow"], why="the answer at the agent")


async def test_permission_asked_while_another_tab_is_shown_is_answered_on_return(workspace):
    async with workspace.app(size=(110, 40), agent=peer("scripted")) as ui:
        await ui.until_agent_ready()
        first = ui.selected_tab
        await ui.write_draft(script({"wait": "hidden"}, {"ask": "PERMISSION_WHILE_HIDDEN"}))
        await ui.press("enter")
        await ui.new_session()
        workspace.release("hidden")
        await ui.until(lambda: {"wait": "hidden"} in workspace.steps_done(), why="the agent to reach its question")
        await ui.step(0.5)
        await ui.select_tab(first)
        await ui.until_shows("a Allow")
        assert ui.shows("PERMISSION_WHILE_HIDDEN")
        await ui.press("a")
        await ui.until(lambda: answers(workspace) == ["Allow"], why="the answer at the agent")


async def test_leaving_and_returning_keeps_a_pending_permission_question(workspace):
    async with workspace.app(size=(110, 40), agent=peer("scripted")) as ui:
        await ui.until_agent_ready()
        first = ui.selected_tab
        await ui.write_draft(script({"ask": "PERMISSION_KEPT"}))
        await ui.press("enter")
        await ui.until_shows("PERMISSION_KEPT")
        other = await ui.new_session()
        assert not ui.shows("a Allow")
        await ui.select_tab(first)
        await ui.until_shows("PERMISSION_KEPT")
        await ui.press("a")
        await ui.until(lambda: answers(workspace) == ["Allow"], why="the answer at the agent")
