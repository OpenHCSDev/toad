"""Textual-facing: turn and compaction facts from Core's owners, delivered as ACP updates, drive the conversation's activity line."""

from pathlib import Path
import subprocess
import sys

from agent_comms.acp_extension import CompactionChangedUpdate, GoalChangedUpdate, TurnChangedUpdate, decode_updates
from agent_comms.child_process import SpawnedProcess
from agent_comms.coordinator import Coordination


PRODUCER = Path(__file__).resolve().parents[1] / "support/peers/typed_turn_events.py"


async def test_phase_events_from_core_owners_reach_the_turn_activity_and_a_finished_cut_is_refused(workspace):
    import json

    from toad.widgets.conversation import TurnActivity

    command = (sys.executable, str(PRODUCER), str(workspace.roots.attempt / "producer-wire"), str(workspace.project))
    with SpawnedProcess.launch(command, output=subprocess.PIPE) as child:
        stdout, stderr = await Coordination.run_worker(child.process.communicate)
        outcome = child.reap()
    assert outcome.successful, (outcome, stderr.decode())
    requests = iter(json.loads(line) for line in stdout.splitlines())

    async with workspace.app(size=(90, 30)) as ui:
        agent = ui.detached_agent("pilot")
        try:
            ui.attach_agent(agent)
            view = ui.conversation
            await ui.step()

            async def consume_until(member):
                for request in requests:
                    assert await agent.server.call(request) is None
                    await ui.step()
                    for fact in decode_updates(request["params"]["update"].get("_meta")):
                        if isinstance(fact, member):
                            return fact
                raise AssertionError(f"the producer did not publish {member.__name__}")

            active = await consume_until(TurnChangedUpdate)
            turn_id = active.state.managed_id
            assert agent.current_turn.managed_id == view.turns.managed_id == turn_id
            assert agent.current_turn.busy and view.turns.owner.busy
            await consume_until(CompactionChangedUpdate)
            assert "Compacting context" in str(view.query_one(TurnActivity).render())
            # Pi runs the compaction and reports its start and its end; there is no progress in between.
            await consume_until(CompactionChangedUpdate)
            assert "Compacting context" not in view.turns.owner.activity
            stale = await consume_until(TurnChangedUpdate)
            assert not stale.state.busy and not stale.state.matches(turn_id)
            assert agent.current_turn.managed_id == view.turns.managed_id == turn_id
            terminal = await consume_until(TurnChangedUpdate)
            assert not terminal.state.busy and terminal.state.matches(turn_id)
            assert agent.current_turn.managed_id is view.turns.managed_id is None
            assert not agent.current_turn.busy and not view.turns.owner.busy
            await consume_until(GoalChangedUpdate)
            assert view.goal_display.snapshot is None and view.goal_execution is None
            assert not list(requests)
        finally:
            await agent.stop()
