"""A real owner save updates the mounted goal preview, independently of progress."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.acp import CommsAgent
from agent_comms.operations import wire
from textual.widgets import Static

from toad.acp.agent import Agent
from toad.acp.messages import GoalSnapshotUpdate
from toad.app import ToadApp
from toad.screens.goal_edit import GoalEdit
from toad.widgets.goal_text import GoalText


async def main():
    with TemporaryDirectory(prefix="toad-goal-objective-", dir="/var/tmp") as directory:
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
            agent = Agent(
                project, {"name": "agent-comms", "run_command": {"*": "true"}}, None
            )
            agent._coordination_root = str(comms.root)
            agent._coordination_thread = session
            original = await agent.update_goal(
                "set",
                "Work on draft PR #17 and report remaining gaps. "
                + "Detailed acceptance criteria. " * 30,
            )
            comms.update_goal(
                session,
                "active",
                goal_id=original.id,
                progress="Renamed parent thread to pr17 and forked implementation.",
            )
            app = ToadApp(project_dir=str(project))
            async with app.run_test(size=(110, 35)) as pilot:
                await pilot.pause()
                conversation = app.screen.conversation
                conversation.set_reactive(type(conversation).agent, agent)
                conversation.agent_ready = True
                await conversation.refresh_goal()
                await pilot.pause()
                for objective in ("Short updated goal", "Second short goal"):
                    await pilot.click("#goal-edit")
                    await pilot.pause()
                    editor = app.screen
                    assert isinstance(editor, GoalEdit)
                    assert (
                        editor.editor.text == comms.registry.require(session).goal.text
                    )
                    assert "Renamed parent thread" not in editor.editor.text
                    assert "Progress (read-only): Renamed parent thread" in str(
                        editor.query_one(".goal-edit-progress", Static).render()
                    )
                    editor.editor.prompt_text_area.focus()
                    await pilot.pause()
                    editor.editor.prompt_text_area.action_select_all()
                    await pilot.press("backspace", *list(objective))
                    assert editor.editor.text == objective, repr(editor.editor.text)
                    await pilot.pause()
                    if objective.startswith("Second"):
                        await pilot.press("enter")
                    else:
                        await pilot.click("#goal-save")
                    await pilot.pause()
                    assert not isinstance(app.screen, GoalEdit)
                    current = comms.registry.require(session).goal
                    assert current.id == original.id and current.text == objective
                    assert conversation.goal == current
                    conversation.post_message(GoalSnapshotUpdate(original, None))
                    await pilot.pause()
                    assert conversation.goal == current, (
                        "Old notification must not overwrite the canonical snapshot"
                    )
                    summary = conversation.query_one(".goal-summary", GoalText)
                    assert objective in str(summary.render()), str(summary.render())
                    frame = "\n".join(
                        strip.text for strip in app.screen._compositor.render_strips()
                    )
                    assert " ".join(objective.split()[:3]) in frame, frame
                    assert objective.split()[-1] in frame, frame
                    assert "Objective:" in frame and "Progress:" in frame, frame
                    assert "Renamed parent thread" in frame, frame
                long_objective = (
                    "Work on draft PR #17. "
                    + "Preserve detailed acceptance criteria. " * 30
                    + "TAIL_COORDINATOR"
                )
                current = await agent.edit_goal(current, long_objective)
                await conversation.refresh_goal()
                await pilot.pause()
                frame = "\n".join(
                    strip.text for strip in app.screen._compositor.render_strips()
                )
                assert f"rev {current.revision}" in frame
                assert (
                    "Scroll for full text" in frame and "TAIL_COORDINATOR" not in frame
                )
                await pilot.click("#goal-expand")
                await pilot.pause()
                assert "TAIL_COORDINATOR" in app.screen.goal.text
                await pilot.press("escape")
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
                first = asyncio.create_task(conversation.refresh_goal())
                await asyncio.wait_for(started.wait(), 2)
                pause = asyncio.create_task(conversation.change_goal("paused"))
                async with asyncio.timeout(2):
                    while comms.registry.require(session).goal.status != "paused":
                        await asyncio.sleep(0.01)
                clear = asyncio.create_task(conversation.change_goal("clear"))
                async with asyncio.timeout(2):
                    while comms.registry.require(session).goal is not None:
                        await asyncio.sleep(0.01)
                # Let both mutation callers invalidate the in-flight read.
                await asyncio.sleep(0.02)
                release.set()
                await asyncio.gather(first, pause, clear)
                # Mutation preflights now also read the canonical owner snapshot.
                assert reads >= 2, reads
                assert conversation.goal is None and conversation.goal_execution is None
                conversation.post_message(GoalSnapshotUpdate(original, None))
                await pilot.pause()
                assert conversation.goal is None
        finally:
            await owner.shutdown()
    print(
        "goal objective: two actual runtime owner edits update mounted compositor; progress remains separate"
    )


if __name__ == "__main__":
    asyncio.run(main())
