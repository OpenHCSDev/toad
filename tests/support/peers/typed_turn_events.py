"""Prints, as JSON-RPC ``session/update`` lines, what Core's own turn owners publish for a compaction.

Not an ACP agent: it runs Core's registry-backed turn and compaction owners on a wire of its own
(``<wire>``) and writes what they would send to a client. It runs no model and no native input.
Usage: ``typed_turn_events.py <wire> <project>``.
"""

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from functools import partial
from pathlib import Path

from agent_comms import agent_events
from agent_comms.acp import CommsAgent
from agent_comms.agent_event_updates import AcpEventConsumer
from agent_comms.comms import wire
from agent_comms.coordinator import Coordination

SESSION = "pilot"


class Pipe:
    async def session_update(self, session_id, update):
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": update.model_dump(mode="json", by_alias=True, exclude_none=True),
        }}), flush=True)


async def produce(wire_root: Path, project: Path):
    # Inherited caller names must not select a different participant during same-process retirement.
    for key in ("PI_AGENT_ID", "AGENT_COMMS_THREAD"):
        os.environ.pop(key, None)
    async with AsyncExitStack() as resources:
        project.mkdir(parents=True, exist_ok=True)
        comms = await Coordination.run_worker(partial(wire, wire_root))
        producer = CommsAgent(comms, runtime_enabled=False, auto_wake=False)
        producer.on_connect(Pipe())
        resources.push_async_callback(producer.shutdown)

        def declare():
            thread = producer.sessions.declare_thread(str(project))
            resources.push_async_callback(Coordination.run_worker, partial(comms.owners.stop, thread.name))
            return thread

        thread = await Coordination.run_worker(declare)
        await producer.sessions.bind_owned(thread, SESSION)
        name = producer.sessions.require(SESSION)
        async with AsyncExitStack() as turns:
            retired_owner = await Coordination.run_worker(partial(
                producer.turns.acquire_turn, turns, SESSION, name, "retired-producer", "Authored protocol; no input"))
        retired = await Coordination.run_worker(partial(producer.turns.current_turn_update, SESSION))
        async with AsyncExitStack() as turns:
            await Coordination.run_worker(partial(
                producer.turns.acquire_turn, turns, SESSION, name, "actual-producer", "Authored protocol; no input"))
            await producer.turns.publish_turn_state(
                AcpEventConsumer(producer, SESSION, producer.sessions.client))
            await producer._emit_event(SESSION, agent_events.CompactionStart())
            await producer._emit_event(SESSION, agent_events.CompactionEnd(
                summary="Authored phase observation; not a native committed summary"))
            assert await Coordination.run_worker(partial(
                comms.agents.finish_turn, retired_owner.turn_lease)) is None
            # An earlier finished cut: the current binding must refuse it.
            await producer._emit_event(SESSION, retired)
        await producer.turns.goals.sync_goal_execution(SESSION, name)


if __name__ == "__main__":
    asyncio.run(produce(Path(sys.argv[1]), Path(sys.argv[2])))
