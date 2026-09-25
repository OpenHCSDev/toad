"""Mounted goal UI polls the actual owner without notification or local mutations."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms import Thread
from agent_comms.acp import CommsAgent
from agent_comms.operations import wire
from textual.containers import VerticalScroll
from textual.widgets import Static

from toad.acp.agent import Agent
from toad.app import ToadApp
from toad.screens.goal_details import GoalDetails
from toad.screens.goal_edit import GoalEdit
from toad.widgets.goal_bar import GoalBar, GoalControl, StandbyPulse
from toad.widgets.throbber import Throbber


async def until(predicate, timeout=4):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


async def main():
    with TemporaryDirectory(prefix="toad-goal-server-", dir="/var/tmp") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
            AGENT_COMMS_AGENT_MODELS="openrouter/fake",
        )
        comms = wire(root / "wire")
        project = root / "project"
        project.mkdir()
        owner = CommsAgent(
            comms,
            agent_bin="pi",
            agent_args=["--provider", "openrouter", "--model", "fake"],
            runtime_enabled=True,
            auto_wake=False,
        )
        try:
            session = (await owner.new_session(cwd=str(project))).session_id
            comms.register(Thread("peer", frozenset(), str(project)))
            agent = Agent(
                project, {"name": "agent-comms", "run_command": {"*": "true"}}, None
            )
            agent._coordination_root = str(comms.root)
            agent._coordination_thread = session
            goal = await agent.update_goal(
                "set",
                "OBJECTIVE_BEGIN "
                + "Fully wrapped acceptance criteria. " * 40
                + " OBJECTIVE_END",
            )
            comms.update_goal(
                session,
                "standby",
                goal_id=goal.id,
                wait_for=["peer"],
                progress="Progress details. " * 40 + " PROGRESS_END",
            )
            app = ToadApp(project_dir=str(project))
            async with app.run_test(size=(90, 35)) as pilot:
                # A headless driver cannot answer terminal color probes.
                app.theme = "textual-dark"
                await pilot.pause()
                conversation = app.screen.conversation
                conversation.set_reactive(type(conversation).agent, agent)
                conversation.agent_ready = True
                # No ACP subscriber/push is connected: only the visible timer can load this.
                await until(lambda: conversation.goal_execution is not None)
                await pilot.pause()
                bar = conversation.query_one(GoalBar)
                assert "Standby" in str(bar.query_one(".goal-header", Static).render())
                assert conversation.goal.status == "active"
                pulse = bar.query_one(StandbyPulse)
                assert pulse.active
                throbber = conversation.query_one(Throbber)
                throbber.busy = True
                await pilot.pause()
                assert pulse.active, (
                    "A prior turn's local throbber must not hide backend standby"
                )
                throbber.busy = False
                document = bar.query_one(".goal-document", VerticalScroll)
                assert document.max_scroll_y > 0
                assert document.size.height <= 7
                assert bar.region.bottom <= conversation.prompt.region.y
                document.scroll_end(animate=False)
                await pilot.pause()
                frame = "\n".join(
                    strip.text for strip in app.screen._compositor.render_strips()
                )
                assert "PROGRESS_END" in frame, (
                    frame,
                    document.scroll_y,
                    document.max_scroll_y,
                    document.region,
                    bar.region,
                    conversation.goal.progress,
                )
                document.scroll_home(animate=False)
                await pilot.pause()
                assert "OBJECTIVE_BEGIN" in "\n".join(
                    strip.text for strip in app.screen._compositor.render_strips()
                )
                for width, height in ((86, 28), (120, 40), (65, 22)):
                    await pilot.resize_terminal(width, height)
                    await pilot.pause()
                    document.scroll_end(animate=False)
                    await pilot.pause()
                    frame = "\n".join(
                        strip.text for strip in app.screen._compositor.render_strips()
                    )
                    assert "PROGRESS_END" in frame, frame
                    assert (
                        bar.region.y >= 0
                        and bar.region.bottom <= conversation.prompt.region.y
                    )
                    assert all(
                        control.region.y >= 0 and control.region.bottom <= height
                        for control in bar.query(GoalControl)
                    )
                    document.scroll_home(animate=False)
                    await pilot.pause()
                    app.save_screenshot(
                        filename=f"toad-goal-layout-{width}x{height}.svg",
                        path="/var/tmp",
                    )
                await pilot.resize_terminal(90, 35)
                await pilot.pause()
                # Current details remain the same server projection while the modal is open.
                await pilot.click("#goal-history")
                await pilot.pause()
                details = app.screen
                assert isinstance(details, GoalDetails)
                current = comms.registry.require(session).goal
                comms.update_goal(
                    session,
                    "edit",
                    text="Changed through owner backend",
                    goal_id=current.id,
                    expected_goal=current,
                    owner_action=True,
                )
                await until(
                    lambda: details.goal.text == "Changed through owner backend"
                )
                assert "Changed through owner backend" in str(
                    details.query_one("#goal-current-objective", Static).render()
                )
                await pilot.press("escape")
                await pilot.click("#goal-edit")
                await pilot.pause()
                editor = app.screen
                assert isinstance(editor, GoalEdit)
                editor.editor.text = "UNSAVED DRAFT"
                current = comms.registry.require(session).goal
                comms.update_goal(
                    session,
                    "edit",
                    text="Concurrent owner edit",
                    goal_id=current.id,
                    expected_goal=current,
                    owner_action=True,
                )
                await until(lambda: conversation.goal.text == "Concurrent owner edit")
                assert editor.editor.text == "UNSAVED DRAFT"
                await pilot.press("escape")
                # Every mutation goes through owner RPC, then a canonical read.
                await conversation.change_goal("paused")
                assert conversation.goal.status == "paused" and not pulse.active
                await conversation.change_goal("active")
                assert conversation.goal.status == "active"
                # Actual server error marks the retained snapshot unavailable, never standby.
                read = comms.goal_snapshot

                def unavailable(_name):
                    raise OSError("Owner temporarily unavailable")

                comms.goal_snapshot = unavailable
                await until(lambda: conversation.goal_unavailable)
                assert "unavailable" in str(
                    bar.query_one(".goal-header", Static).render()
                )
                assert not pulse.active
                assert all(control.disabled for control in bar.query(GoalControl)
                           if control.id != "goal-collapse")
                assert not bar.query_one("#goal-collapse", GoalControl).disabled
                comms.goal_snapshot = read
                await until(lambda: not conversation.goal_unavailable)
                await conversation.change_goal("clear")
                assert conversation.goal is None and not bar.display
                # A stalled read is bounded; mutations have no automatic timeout/replay.
                request = agent._owner_request

                async def stalled(method, **params):
                    await asyncio.Event().wait()

                agent._owner_request = stalled
                try:
                    await asyncio.wait_for(agent.get_goal_snapshot(), 3.5)
                except TimeoutError:
                    pass
                else:
                    raise AssertionError("Snapshot read did not time out")
                finally:
                    agent._owner_request = request
        finally:
            await owner.shutdown()
    print(
        "goal server poll: actual owner read/mutations, standby, scrolling, live modal/draft, outage recovery and bounded read pass"
    )


if __name__ == "__main__":
    asyncio.run(main())
