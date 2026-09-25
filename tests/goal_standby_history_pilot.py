"""Mounted goal projections, stable editing, mentions, and backend revision history."""

import asyncio
import os
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms import (
    Goal,
    GoalExecution,
    GoalExecutionState,
    GoalWaitTarget,
    Thread,
    wire,
)
from textual.content import Content
from textual.widgets import Button, Static

from toad.acp.messages import GoalSnapshotUpdate
from toad.app import ToadApp
from toad.screens.goal_details import GoalDetails
from toad.screens.goal_edit import GoalEdit
from toad.widgets.goal_bar import GoalBar
from toad.widgets.throbber import Throbber


class GoalOwner:
    def __init__(self):
        self.goal = Goal(
            "Coordinate with @peer", "stable-goal", progress="Keep evidence", revision=4
        )
        self.execution = GoalExecution(
            GoalExecutionState.STANDBY, self.goal.id, (GoalWaitTarget("peer", 1.0),)
        )
        self.requests = []
        self.reject = True

    async def get_goal_snapshot(self):
        return self.goal, self.execution

    async def get_goal(self):
        return self.goal

    async def get_goal_execution(self):
        return self.execution

    async def edit_goal(self, expected, text):
        self.requests.append((expected.id, expected.revision, text))
        if self.reject:
            raise ValueError("Goal changed; refresh before editing")
        self.goal = replace(self.goal, text=text, revision=self.goal.revision + 1)
        return self.goal

    async def get_goal_history(self, goal_id):
        assert goal_id == self.goal.id
        return [
            {
                "sequence": 1,
                "kind": "baseline",
                "observed_at": 1000.0,
                "before": None,
                "after": asdict(
                    replace(self.goal, text="HISTORICAL_OBJECTIVE", revision=4)
                ),
            },
            {
                "sequence": 2,
                "kind": "transition",
                "observed_at": 1001.0,
                "before": asdict(replace(self.goal, revision=4)),
                "after": asdict(self.goal),
            },
        ]

    def get_info(self):
        return Content("Goal owner")

    async def stop(self):
        pass


async def main():
    with TemporaryDirectory(prefix="toad-goal-standby-", dir="/var/tmp") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        comms = wire(root / "wire")
        comms.registry.register(
            Thread(name="peer", tags=frozenset(), worktree=str(root))
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            owner = GoalOwner()
            conversation.set_reactive(type(conversation).agent, owner)
            conversation.agent_ready = True
            conversation.goal = owner.goal
            conversation.goal_execution = owner.execution
            conversation.prompt.text = "Composer draft stays"
            await pilot.pause()
            bar = conversation.query_one(GoalBar)
            status = bar.query_one(".goal-execution", Static)
            assert status.display
            rendered = bar.query_one(".goal-summary", Static).render()
            assert any(
                not isinstance(span.style, str)
                and (span.style.meta or {}).get("@click") == ("open_target", ("peer",))
                for span in rendered.spans
            ), "Goal mentions must use existing thread navigation"
            assert "Standby" in str(status.render()) and "@peer" in str(status.render())
            throbber = conversation.query_one(Throbber)
            throbber.busy = True
            await pilot.pause()
            assert not status.display, (
                "Thinking/compacting takes precedence over standby"
            )
            throbber.busy = False
            await pilot.pause()
            assert status.display
            conversation.goal_execution = GoalExecution(
                GoalExecutionState.RUNNABLE, owner.goal.id
            )
            await pilot.pause()
            assert not status.display, "Goal prose must never infer standby"
            conversation.goal_execution = owner.execution
            conversation.goal = replace(owner.goal, status="paused")
            await pilot.pause()
            assert not status.display, (
                "A previous standby projection cannot override paused goal state"
            )
            conversation.goal = owner.goal
            await pilot.pause()
            await pilot.click("#goal-edit")
            await pilot.pause()
            editor = app.screen
            assert isinstance(editor, GoalEdit)
            editor.query_one("#goal-save", Button).active_effect_duration = 0
            editor.editor.text = "Ask @pe"
            editor.editor.prompt_text_area.move_cursor((0, 7))
            editor.editor.refresh_mentions(force=True)
            assert editor.editor._options[0].name == "peer"
            editor.editor.accept_mention()
            assert editor.editor.text == "Ask @peer "
            await pilot.pause()
            await pilot.click("#goal-save")
            await pilot.pause()
            assert app.screen is editor
            assert "Goal changed" in str(
                editor.query_one("#goal-edit-error", Static).render()
            ), (
                owner.requests,
                "\n".join(
                    strip.text for strip in app.screen._compositor.render_strips()
                ),
            )
            assert conversation.goal.text == "Coordinate with @peer"
            assert editor.editor.text == "Ask @peer ", (
                "Rejected edit keeps user's draft"
            )
            owner.reject = False
            await pilot.click("#goal-save")
            await pilot.pause()
            assert not isinstance(app.screen, GoalEdit), (
                owner.requests,
                "\n".join(
                    strip.text for strip in app.screen._compositor.render_strips()
                ),
            )
            assert (
                conversation.goal.id == "stable-goal"
                and conversation.goal.revision == 5
            )
            assert owner.requests == [("stable-goal", 4, "Ask @peer")] * 2
            assert conversation.prompt.text == "Composer draft stays"
            await pilot.click("#goal-expand")
            await pilot.pause()
            assert isinstance(app.screen, GoalDetails)
            frame = "\n".join(
                strip.text for strip in app.screen._compositor.render_strips()
            )
            assert (
                "HISTORICAL_OBJECTIVE" in frame
                and "baseline" in frame
                and "observed" in frame
            )
            await pilot.press("escape")
            assert conversation.prompt.text == "Composer draft stays"
            pushed = replace(
                owner.goal, text="Backend edited the same goal", revision=6
            )
            owner.goal = pushed
            conversation.post_message(GoalSnapshotUpdate(pushed, owner.execution))
            await pilot.pause()
            assert conversation.goal == pushed
            assert "Backend edited the same goal" in str(
                bar.query_one(".goal-summary", Static).render()
            ), str(bar.query_one(".goal-summary", Static).render())
            owner.goal, owner.execution = None, None
            conversation.post_message(GoalSnapshotUpdate(None, None))
            await pilot.pause()
            assert conversation.goal is None and conversation.goal_execution is None
            assert not bar.display
    print(
        "goal UI: authoritative standby, busy precedence, mention completion, same-ID edit, rejection draft, revision history"
    )


if __name__ == "__main__":
    asyncio.run(main())
