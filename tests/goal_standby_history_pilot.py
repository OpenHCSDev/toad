from agent_comms.acp_extension import GoalChangedUpdate
from toad.acp.messages import CommsUpdated
from runtime_fixture import wait_channel_roster

from toad.goal_display import GoalDisplay

import asyncio
import os
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.acp_extension import GoalChangedUpdate
from agent_comms.comms import wire
from agent_comms.goal_presentation import (
    GoalExecution,
    GoalExecutionState,
    GoalWaitTarget,
)
from agent_comms.goal_states import PausedGoal
from agent_comms.goals import Goal
from agent_comms.threads import Thread
from textual.content import Content
from textual.widgets import Button, Static

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
        return (self.goal, self.execution)

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
                "after": replace(
                    self.goal, text="HISTORICAL_OBJECTIVE", revision=4
                ).to_wire(),
            },
            {
                "sequence": 2,
                "kind": "transition",
                "observed_at": 1001.0,
                "before": replace(self.goal, revision=4).to_wire(),
                "after": self.goal.to_wire(),
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
            await wait_channel_roster(app, pilot, "#all")
            conversation = app.selected_session.conversation
            owner = GoalOwner()
            conversation.set_reactive(type(conversation).agent, owner)
            conversation.agent_ready = True
            conversation.goal_display = GoalDisplay.current(owner.goal)
            conversation.goal_execution = owner.execution
            conversation.prompt.text = "Composer draft stays"
            await pilot.pause()
            bar = conversation.query_one(GoalBar)
            status = bar.query_one(".goal-execution", Static)
            assert status.display
            rendered = bar.query_one(".goal-summary", Static).render()
            assert any(
                (
                    not isinstance(span.style, str)
                    and (span.style.meta or {}).get("@click")
                    == ("open_target", ("peer",))
                    for span in rendered.spans
                )
            ), "Goal mentions must use existing thread navigation"
            assert "Standby" in str(status.render()) and "@peer" in str(status.render())
            throbber = conversation.query_one(Throbber)
            throbber.busy = True
            await pilot.pause()
            assert status.display, (
                "Canonical standby remains visible while the previous turn settles"
            )
            throbber.busy = False
            await pilot.pause()
            assert status.display
            standby_execution = owner.execution
            owner.execution = GoalExecution(GoalExecutionState.RUNNABLE, owner.goal.id)
            await conversation.goal_observation.refresh()
            await pilot.pause()
            assert not status.display, "Goal prose must never infer standby"
            owner.execution = standby_execution
            active_goal = owner.goal
            owner.goal = replace(owner.goal, state=PausedGoal())
            await conversation.goal_observation.refresh()
            await pilot.pause()
            assert not status.display, (
                "A previous standby projection cannot override paused goal state"
            )
            owner.goal = active_goal
            await conversation.goal_observation.refresh()
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
                    (strip.text for strip in app.screen._compositor.render_strips())
                ),
            )
            assert conversation.goal_display.snapshot.text == "Coordinate with @peer"
            assert editor.editor.text == "Ask @peer ", (
                "Rejected edit keeps user's draft"
            )
            owner.reject = False
            await pilot.click("#goal-save")
            await pilot.pause()
            assert not isinstance(app.screen, GoalEdit), (
                owner.requests,
                "\n".join(
                    (strip.text for strip in app.screen._compositor.render_strips())
                ),
            )
            assert (
                conversation.goal_display.snapshot.id == "stable-goal"
                and conversation.goal_display.snapshot.revision == 5
            )
            assert owner.requests == [("stable-goal", 4, "Ask @peer")] * 2
            assert conversation.prompt.text == "Composer draft stays"
            await pilot.click("#goal-history")
            await pilot.pause()
            assert isinstance(app.screen, GoalDetails)
            frame = "\n".join(
                (strip.text for strip in app.screen._compositor.render_strips())
            )
            assert (
                "HISTORICAL_OBJECTIVE" in frame
                and "baseline" in frame
                and ("observed" in frame)
            )
            await pilot.press("escape")
            assert conversation.prompt.text == "Composer draft stays"
            pushed = replace(
                owner.goal, text="Backend edited the same goal", revision=6
            )
            owner.goal = pushed
            conversation.post_message(CommsUpdated(GoalChangedUpdate(pushed, owner.execution)))
            await pilot.pause()
            assert conversation.goal_display.snapshot == pushed
            assert "Backend edited the same goal" in str(
                bar.query_one(".goal-summary", Static).render()
            ), str(bar.query_one(".goal-summary", Static).render())
            owner.goal, owner.execution = None, None
            conversation.post_message(CommsUpdated(GoalChangedUpdate(None, None)))
            await pilot.pause()
            assert conversation.goal_display.snapshot is None and conversation.goal_execution is None
            assert not bar.display
        await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "goal UI: authoritative standby through turn settlement, mention completion, same-ID edit, rejection draft, revision history"
    )


if __name__ == "__main__":
    asyncio.run(main())
