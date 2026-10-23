"""Core turn and compaction publications preserve custody in a mounted conversation."""

from pathlib import Path
import subprocess
import sys

from agent_comms.acp_extension import CompactionChangedUpdate, GoalChangedUpdate, TurnChangedUpdate, decode_updates
from agent_comms.child_process import SpawnedProcess
from agent_comms.coordinator import Coordination
from agent_comms.goal_presentation import IdleGoalExecution
from agent_comms.goals import NoGoal
from support.agents import deliver


PRODUCER = Path(__file__).resolve().parents[1] / "support/peers/typed_turn_events.py"


async def test_core_compaction_publications_retain_the_active_turn_and_refuse_a_finished_cut(workspace):
    import json

    command = (sys.executable, str(PRODUCER), str(workspace.roots.wire), str(workspace.project))
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
                    await deliver(agent, request["params"]["update"], session_id=request["params"]["sessionId"])
                    await ui.step()
                    for fact in decode_updates(request["params"]["update"].get("_meta")):
                        if isinstance(fact, member):
                            return fact
                raise AssertionError(f"the producer did not publish {member.__name__}")

            active = await consume_until(TurnChangedUpdate)
            turn_id = active.state.active.id
            assert agent.current_turn.managed_id == view.turns.managed_id == turn_id
            assert agent.current_turn.busy and view.turns.owner.busy
            await consume_until(CompactionChangedUpdate)
            assert "Compacting context" in view.turns.owner.activity
            # Pi runs the compaction and reports its start and its end; there is no progress in between.
            await consume_until(CompactionChangedUpdate)
            assert "Compacting context" not in view.turns.owner.activity
            stale = await consume_until(TurnChangedUpdate)
            assert not stale.state.active.phase.busy and not stale.state.matches(turn_id)
            assert agent.current_turn.managed_id == view.turns.managed_id == turn_id
            terminal = await consume_until(TurnChangedUpdate)
            assert not terminal.state.active.phase.busy and terminal.state.matches(turn_id)
            assert agent.current_turn.managed_id is view.turns.managed_id is None
            assert not agent.current_turn.busy and not view.turns.owner.busy
            await consume_until(GoalChangedUpdate)
            assert view.goal_display.snapshot == NoGoal() and view.goal_execution == IdleGoalExecution()
            assert not list(requests)
        finally:
            await agent.stop()
