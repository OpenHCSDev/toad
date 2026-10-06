"""Original registry leases -> ACP JSON -> actual mounted Toad consumer.

This authored protocol control runs no native input, model or compaction. Its
phase events exercise the actual turn owner and notification/presentation path.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
from functools import partial
import json
import os
from pathlib import Path
import subprocess
import sys

from mcp_observation_fixture import AGENT_DATA, turn_source
from agent_comms import agent_events
from agent_comms.acp_extension import (
    CompactionChangedUpdate, GoalChangedUpdate, TurnChangedUpdate, decode_updates,
)
from agent_comms.child_process import ParentedProcess
from agent_comms.compaction_progress import CompactionSourceProgress
from agent_comms.coordinator import Coordination
from agent_comms.field_codec import FieldCodec


class Pipe:
    async def session_update(self, session_id, update):
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": update.model_dump(mode="json", by_alias=True, exclude_none=True),
        }}), flush=True)


async def produce(root: Path):
    session_id = "pilot"
    async with turn_source(root, session_id) as producer:
        name = producer.sessions.require(session_id)
        async with AsyncExitStack() as custody:
            retired_owner = await Coordination.run_worker(partial(
                producer.turns.acquire_turn, custody, session_id, name,
                "retired-producer", "Authored protocol; no input",
            ))
        retired = await Coordination.run_worker(partial(producer.turns.current_turn_update, session_id))
        producer.on_connect(Pipe())
        async with AsyncExitStack() as custody:
            await Coordination.run_worker(partial(
                producer.turns.acquire_turn, custody, session_id, name,
                "actual-producer", "Authored protocol; no input",
            ))
            await producer.turns.replay_turn_state(session_id)
            await producer._emit_event(session_id, agent_events.CompactionStart())
            await producer._emit_event(session_id, agent_events.CompactionSummaryProgress(
                operation_id="authored-progress",
                source=CompactionSourceProgress(50, 100, "authored", 1, 2),
            ))
            await producer._emit_event(session_id, agent_events.CompactionEnd(
                summary="Authored phase observation; not a native committed summary",
            ))
            assert await Coordination.run_worker(partial(
                producer._comms.agents.finish_turn, retired_owner.turn_lease,
            )) is None
            # This is an authentic earlier finished cut. The current binding
            # must refuse it, while the backend's exact stale lease CAS refuses.
            await producer._emit_event(session_id, retired)
        await producer.turns.goals.sync_goal_execution(session_id, name)


async def main(root: Path):
    from runtime_fixture import ToadApp
    from toad.acp.agent import Agent
    from toad.agent_schema import AgentDefinition
    from toad.screens.main import MainScreen
    from toad.widgets.conversation import TurnActivity

    root.mkdir(parents=True, exist_ok=False)
    env = {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
           "XDG_STATE_HOME": str(root / "state"), "AGENT_COMMS_ROOT": str(root / "wire")}
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        command = (sys.executable, str(Path(__file__).resolve()), "--produce", str(root / "producer"))
        with ParentedProcess.launch(command, output=subprocess.PIPE) as child:
            identity = FieldCodec.encode(child.identity)
            stdout, stderr = await Coordination.run_worker(child.process.communicate)
            outcome = child.reap()
            (root / "producer.jsonl").write_bytes(stdout)
            (root / "producer.stderr").write_bytes(stderr)
            (root / "producer-exit.json").write_text(json.dumps({
                "identity": identity, "outcome": FieldCodec.encode(outcome),
            }, indent=2) + "\n")
            assert outcome.successful, (outcome, stderr.decode())
        requests = iter(json.loads(line) for line in stdout.splitlines())
        app = ToadApp(project_dir=str(root / "producer" / "project"))
        async with app.run_test(size=(90, 30)) as pilot:
            session = app.selected_session
            assert isinstance(session, MainScreen)
            await session.wait_content_ready()
            agent = Agent(root / "producer" / "project", AgentDefinition.decode(AGENT_DATA), "pilot")
            try:
                view = session.conversation
                view.agent = agent
                await pilot.pause()

                async def consume_until(member):
                    for request in requests:
                        assert await agent.server.call(request) is None
                        await pilot.pause()
                        for fact in decode_updates(request["params"]["update"].get("_meta")):
                            if isinstance(fact, member):
                                return fact
                    raise AssertionError(f"Original producer did not publish {member.__name__}")

                active = await consume_until(TurnChangedUpdate)
                turn_id = active.state.managed_id
                assert agent.current_turn.managed_id == view.turns.managed_id == turn_id
                assert agent.current_turn.busy and view.turns.owner.busy
                await consume_until(CompactionChangedUpdate)
                assert "Compacting context" in str(view.query_one(TurnActivity).render())
                progress = await consume_until(CompactionChangedUpdate)
                assert progress.event.source.label in view.turns.owner.activity
                assert progress.event.source.label in str(view.query_one(TurnActivity).render())
                await consume_until(CompactionChangedUpdate)
                assert progress.event.source.label not in view.turns.owner.activity
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
                assert app._exception is None
                (root / "typed-consumer.json").write_text(json.dumps({
                    "source": "canonical registry lease, phase/CAS/goal owners; authored protocol input",
                    "managed_turn": turn_id, "stale_cas_and_finished_cut_refused": True,
                    "phase_progress_mounted": True, "terminal_idle_and_goal_clear": True,
                    "native_inputs": 0, "provider_calls": 0,
                }, indent=2) + "\n")
            finally:
                await agent.stop()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--produce", type=Path)
    command.add_argument("--output", type=Path)
    args = parser.parse_args()
    asyncio.run(produce(args.produce) if args.produce is not None else main(args.output.expanduser().resolve()))
