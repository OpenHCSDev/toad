"""Textual-facing: a plan sent by an ACP agent is drawn as one Plan widget in the conversation and in the sidebar (status markers, completion strike-through animation, reset, return), and malformed plan updates are rejected with a visible note."""
from toad.widgets.side_bar import ThreadSidebar
from toad.agent_origin import AgentAttached

import asyncio
from contextlib import asynccontextmanager
import json
from typing import get_args

from acp.schema import PlanEntryStatus

from toad.agent import AgentBase

from support.agents import peer
from support.textual_steps import painted_text, viewport_text
from toad.plan import PlanStatus
from toad.screens.main import MainScreen
from toad.widgets.note import Note
from toad.widgets.plan import Plan
from toad.widgets.strike_text import Complete, StrikeText
from support.ui import saved_tab

FIRST = {"entries": [{"content": f"ACP_{name}_ITEM", "priority": "high", "status": name}
                     for name in get_args(PlanEntryStatus)]}
ALL_COMPLETED = {"entries": [{**entry, "status": "completed"} for entry in FIRST["entries"]]}
EMPTY = {"entries": []}
ONE_COMPLETED = {"entries": [ALL_COMPLETED["entries"][0]]}


def all_complete(plan: Plan) -> bool:
    """Every entry of a non-empty plan is complete; the plan's entries own this."""
    return bool(plan.entries) and all(entry.status.complete for entry in plan.entries)


async def reveal(ui, source):
    return await ui.revealed(source.query_one(ThreadSidebar))


@asynccontextmanager
async def planning_session(workspace, *plans):
    """The app with the plan peer connected; the prompt of `plans` is sent but the peer waits at each step."""
    async with workspace.app(size=(130, 44), binding=AgentAttached(peer("plan", name="Local ACP plan acceptance", identity="plan-acceptance"))) as ui:
        view = ui.conversation
        await ui.until(lambda: isinstance(view.agent_binding, AgentBase), why="the agent")
        agent = view.agent_binding
        await ui.until(agent.session.settled.is_set, why="the agent session")
        assert agent.session.connected, "Real ACP startup/initialize/newSession failed"
        assert agent.process.process.returncode is None
        sidebar = await reveal(ui, ui.textual[0].selected_session)
        sending = asyncio.create_task(agent.send_prompt(json.dumps(list(plans))))
        try:
            yield ui, view, agent, sidebar, sending
        finally:
            for index in range(len(plans)):
                (workspace.project / f"plan-advance-{index}").touch()
            if not sending.done():
                sending.cancel()
            await asyncio.gather(sending, return_exceptions=True)
            await agent.stop()


def advance(workspace, index):
    (workspace.project / f"plan-advance-{index}").touch()


async def test_every_plan_status_is_drawn_with_its_marker_in_the_conversation_and_the_sidebar(workspace):
    async with planning_session(workspace, FIRST) as (ui, view, agent, sidebar, sending):
        await ui.until(lambda: bool(view.query(Plan)), why="the plan in the conversation")
        plan = view.query_one(Plan)
        await ui.until(lambda: len(plan.query(StrikeText)) == len(FIRST["entries"]), why="an item per entry")
        plan.scroll_visible(animate=False, immediate=True)
        await ui.until(lambda: painted_text(plan, "ACP_pending_ITEM"), why="the plan painted")
        assert not all_complete(plan)
        for entry, raw in zip(plan.entries, FIRST["entries"]):
            assert entry.status is PlanStatus.member_named(raw["status"])
            assert entry.content == raw["content"]
            assert entry.status.marker().strip() in viewport_text(plan)
        await ui.until(lambda: painted_text(sidebar.query_one(Plan), "ACP_pending_ITEM"), why="the sidebar plan painted")
        assert sidebar.query_one(Plan).entries is plan.entries


async def test_completing_a_plan_animates_the_strike_through_once_and_survives_a_resize(workspace):
    async with planning_session(workspace, FIRST, ALL_COMPLETED) as (ui, view, agent, sidebar, sending):
        await ui.until(lambda: bool(view.query(Plan)), why="the plan")
        plan = view.query_one(Plan)
        await ui.until(lambda: len(plan.query(StrikeText)) == len(FIRST["entries"]), why="an item per entry")
        advance(workspace, 0)
        await ui.until(lambda: all_complete(plan), why="the completed plan")
        await ui.until(lambda: len(plan.query(StrikeText)) == len(FIRST["entries"])
                       and list(plan.query(StrikeText))[0].strike_time is not None, why="the strike animation")
        completed = list(plan.query(StrikeText))
        for raw, text in zip(FIRST["entries"], completed):
            if raw["status"] == "completed":
                assert text.completion is Complete and text.strike_time is None
            else:
                assert text.strike_time is not None
        assert len(view.query(Plan)) == 1, "Repeated plan updates appended competing plans"
        await ui.until(lambda: all(text.auto_refresh is None for text in completed), why="the animation to stop")
        assert "ACP_pending_ITEM" in viewport_text(plan)
        await ui.resize(104, 35)
        plan.scroll_visible(animate=False, immediate=True)
        await ui.until(lambda: painted_text(plan, "ACP_pending_ITEM"), why="the plan painted after the resize")


async def test_an_empty_plan_resets_the_view_and_a_retired_sidebar_shows_later_plans_again(workspace):
    async with planning_session(workspace, FIRST, ALL_COMPLETED, EMPTY, ONE_COMPLETED) as (ui, view, agent, sidebar, sending):
        await ui.until(lambda: bool(view.query(Plan)), why="the plan")
        plan = view.query_one(Plan)
        advance(workspace, 0)
        await ui.until(lambda: all_complete(plan), why="the completed plan")
        advance(workspace, 1)
        await sidebar.evict(ui.textual[0].selected_session)
        assert not sidebar.panels
        await ui.until(lambda: not plan.entries and not all_complete(plan), why="the plan to reset")
        await ui.until(lambda: painted_text(plan, "No plan yet"), why="the empty plan painted")
        await sidebar.prepare_presentation()
        await reveal(ui, ui.textual[0].selected_session)
        restored = sidebar.query_one(Plan)
        assert restored.entries is plan.entries
        await ui.until(lambda: painted_text(restored, "No plan yet"), why="the empty plan in the sidebar")
        advance(workspace, 2)
        await ui.until(lambda: all_complete(plan) and len(plan.query(StrikeText)) == 1, why="the one completed item")
        assert plan.query_one(StrikeText).completion is Complete
        assert plan.query_one(StrikeText).strike_time is None
        await ui.until(lambda: painted_text(plan, "ACP_pending_ITEM"), why="the plan painted")
        await ui.until(lambda: painted_text(sidebar.query_one(Plan), "ACP_pending_ITEM"), why="the sidebar plan painted")


async def test_malformed_plan_updates_are_rejected_with_a_visible_note_each(workspace):
    async with planning_session(workspace, FIRST) as (ui, view, agent, sidebar, sending):
        await ui.until(lambda: bool(view.query(Plan)), why="the plan")
        plan = view.query_one(Plan)
        advance(workspace, 0)
        await asyncio.wait_for(sending, 10)
        await ui.until(lambda: len([note for note in view.query(Note)
                                    if "Invalid ACP update rejected" in note.render().plain]) == 3,
                       why="three rejection notes")
        assert plan.entries[0].content == FIRST["entries"][0]["content"]
        assert sidebar.query_one(Plan).entries is plan.entries
        assert ui.failure() is None


async def test_a_plan_sent_while_no_view_shows_the_agent_is_drawn_when_its_view_returns(workspace):
    async with planning_session(workspace, FIRST) as (ui, view, agent, sidebar, sending):
        app = ui.textual[0]
        await ui.until(lambda: bool(view.query(Plan)), why="the plan")
        plan = view.query_one(Plan)
        advance(workspace, 0)
        await asyncio.wait_for(sending, 10)
        source = app.selected_session
        original_process = agent.process.process
        editor = view.prompt.prompt_text_area
        editor.insert("Detached plan draft")
        original_document, original_history = editor.document, editor.history
        await app.session_navigation.new(
            await saved_tab(app),
            lambda: MainScreen(app.project_dir, app.agent_binding.for_session("plan-blank"))
        )
        assert agent.controller.surface.target is None
        detached_plan = {"entries": [{"content": "DETACHED_PLAN_ITEM", "priority": "high", "status": "pending"}]}
        advance(workspace, 0)
        await asyncio.wait_for(agent.send_prompt(json.dumps([detached_plan])), 10)
        await ui.until(lambda: agent.controller.plan_entries is not None
                       and agent.controller.plan_entries[0].content == "DETACHED_PLAN_ITEM",
                       why="the plan held by the detached agent")
        await ui.select_tab(source.id)
        view = ui.conversation
        # Earlier plans stay in the conversation as history; the current one is the controller's.
        await ui.until(lambda: any(candidate.entries is agent.controller.plan_entries for candidate in view.query(Plan)),
                       why="the current plan in the returned view")
        restored_plan = next(c for c in view.query(Plan) if c.entries is agent.controller.plan_entries)
        assert restored_plan is not plan
        assert plan.entries[0].content == "ACP_pending_ITEM"
        restored_plan.scroll_visible(animate=False, immediate=True)
        await ui.until(lambda: painted_text(restored_plan, "DETACHED_PLAN_ITEM"), why="the returned plan painted")
        sidebar = await reveal(ui, source)
        await ui.until(lambda: painted_text(sidebar.query_one(Plan), "DETACHED_PLAN_ITEM"), why="the sidebar plan painted")
        assert restored_plan.entries is agent.controller.plan_entries
        assert sidebar.query_one(Plan).entries is restored_plan.entries
        assert view.agent_binding is agent and agent.process.process is original_process
        assert view.prompt.prompt_text_area.document is original_document
        assert view.prompt.prompt_text_area.history is original_history
        assert view.prompt.text == "Detached plan draft"
        assert ui.failure() is None
