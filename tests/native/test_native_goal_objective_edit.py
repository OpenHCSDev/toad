"""Editing a goal's objective in Toad saves through the real owner and redraws the goal bar; progress stays separate."""

import asyncio
from contextlib import asynccontextmanager

from agent_comms.acp_extension import GoalChangedUpdate
from agent_comms.goal_actions import ActiveGoalAction, ClearGoalAction, GoalPrecondition, PausedGoalAction, SetGoalAction
from textual.widgets import Static

from support.agents import detached
from support.native import owner_server, start_private_native_wire
from support.textual_steps import coordination_update
from toad.core.events import CommsUpdated
from toad.screens.goal_edit import GoalEdit
from toad.widgets.goal_text import GoalText


PROGRESS = "Renamed parent thread to pr17 and forked implementation."


@asynccontextmanager
async def goal_in_toad(workspace, native_package, monkeypatch):
    """A real owner with an active goal and progress, shown in Toad through an agent object on its session."""
    monkeypatch.setenv("AGENT_COMMS_AGENT_MODELS", "openrouter/fake")
    comms = start_private_native_wire(workspace.roots.wire, native_package)
    owner = owner_server(comms, native_package)
    try:
        session = (await owner.new_session(cwd=str(workspace.project))).session_id
        agent = detached(workspace.project)
        agent.coordination = coordination_update(str(comms.root), session)
        first = await agent.update_goal(
            SetGoalAction, "Work on draft PR #17 and report remaining gaps. " + "Detailed acceptance criteria. " * 30)
        comms.goals.update_goal(session, ActiveGoalAction(progress=PROGRESS, expect=GoalPrecondition(goal_id=first.id)))
        async with workspace.app(size=(110, 35)) as ui:
            conversation = ui.conversation
            conversation.set_reactive(type(conversation).agent, agent)
            conversation.bind_agent(agent)
            conversation.agent_ready = True
            await conversation.goal_observation.refresh()
            await ui.step()
            yield ui, agent, comms, session, first
    finally:
        await owner.shutdown()


async def test_objective_edits_save_to_the_owner_and_redraw_the_goal_bar(workspace, native_package, monkeypatch):
    async with goal_in_toad(workspace, native_package, monkeypatch) as (ui, agent, comms, session, first):
        app, pilot = ui.textual
        conversation = ui.conversation
        current = first
        for objective in ("Short updated goal", "Second short goal"):
            await pilot.click("#goal-edit")
            await ui.until(lambda: isinstance(app.screen, GoalEdit), why="the goal editor")
            editor = app.screen
            assert editor.editor.text == comms.registry.require(session).goal.text
            assert "Renamed parent thread" not in editor.editor.text
            assert "Progress (read-only): Renamed parent thread" in str(
                editor.query_one(".goal-edit-progress", Static).render())
            editor.editor.prompt_text_area.focus()
            await ui.step()
            editor.editor.prompt_text_area.action_select_all()
            await ui.press("backspace", *list(objective))
            assert editor.editor.text == objective, repr(editor.editor.text)
            if objective.startswith("Second"):
                await ui.press("enter")
            else:
                await pilot.click("#goal-save")
            await ui.until(lambda: not isinstance(app.screen, GoalEdit), why="the editor to close")
            await ui.until(lambda: comms.registry.require(session).goal.text == objective, why="the saved objective")
            current = comms.registry.require(session).goal
            assert current.id == first.id
            await ui.until(lambda: conversation.goal_display.snapshot == current, why="the saved goal in the bar")
            summary = conversation.query_one(".goal-summary", GoalText)
            assert objective in str(summary.render()), str(summary.render())
            assert ui.shows(" ".join(objective.split()[:3])) and ui.shows(objective.split()[-1])
            assert ui.shows("Objective:") and ui.shows("Progress:")
            assert ui.shows("Renamed parent thread")

        long_objective = ("Work on draft PR #17. " + "Preserve detailed acceptance criteria. " * 30
                          + "TAIL_COORDINATOR")
        current = await agent.edit_goal(current, long_objective)
        await conversation.goal_observation.refresh()
        await ui.until_shows(f"rev {current.revision}")
        assert not ui.shows("Scroll for full text") and not ui.shows("TAIL_COORDINATOR")
        await pilot.click("#goal-history")
        await ui.until(lambda: "TAIL_COORDINATOR" in getattr(getattr(app.screen, "goal", None), "text", ""),
                       why="the full objective in goal details")


async def test_a_slow_goal_read_does_not_bring_back_a_goal_paused_then_cleared(workspace, native_package, monkeypatch):
    async with goal_in_toad(workspace, native_package, monkeypatch) as (ui, agent, comms, session, _first):
        conversation = ui.conversation
        started, release = asyncio.Event(), asyncio.Event()
        read_snapshot = agent.get_goal_snapshot
        reads = 0

        async def delayed_snapshot():
            nonlocal reads
            reads += 1
            snapshot = await read_snapshot()
            if reads == 1:
                started.set()
                await release.wait()
            return snapshot

        agent.get_goal_snapshot = delayed_snapshot
        slow = asyncio.create_task(conversation.goal_observation.refresh())
        await asyncio.wait_for(started.wait(), 2)
        pause = asyncio.create_task(conversation.goal_controls.change(PausedGoalAction))
        await ui.until(lambda: comms.registry.require(session).goal.state.declared_name == "paused",
                       seconds=5, why="the goal paused on the owner")
        clear = asyncio.create_task(conversation.goal_controls.change(ClearGoalAction))
        await ui.until(lambda: comms.registry.require(session).goal is None, seconds=5, why="the goal cleared")
        release.set()
        await asyncio.gather(slow, pause, clear)
        assert reads >= 2, reads
        assert conversation.goal_display.snapshot is None and conversation.goal_execution is None


async def test_a_late_notice_of_an_older_goal_does_not_replace_the_current_one(workspace, native_package, monkeypatch):
    async with goal_in_toad(workspace, native_package, monkeypatch) as (ui, agent, comms, session, first):
        conversation = ui.conversation
        current = await agent.edit_goal(first, "Short updated goal")
        await conversation.goal_observation.refresh()
        assert conversation.goal_display.snapshot == current
        agent.events.publish(CommsUpdated(GoalChangedUpdate(first, None), session_id=agent.session_id))
        await ui.step()
        assert conversation.goal_display.snapshot == current, "A notice of revision " \
            f"{first.revision} replaced the shown revision {current.revision}"
