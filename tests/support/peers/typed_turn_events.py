"""Prints, as JSON-RPC ``session/update`` lines, what Core's own turn owners publish for a compaction.

Not an ACP agent: it runs Core's registry-backed turn and compaction owners on a wire of its own
(``<wire>``) and writes what they would send to a client. It runs no model and no native input.
Usage: ``typed_turn_events.py <wire> <project>``.
"""

import asyncio
from contextlib import AsyncExitStack
from functools import partial
import json
from pathlib import Path
import sys

import agent_comms.agent_events as agent_events
from agent_comms.agent_event_updates import AcpEventConsumer
from agent_comms.controller import SessionUpdateSink
from agent_comms.coordinator import Coordination
from agent_comms.nominal.field_codec import TurnId
from turn_source import turn_source

SESSION = "pilot"


class Pipe(SessionUpdateSink):
    async def publish_update(self, *, session_id, update):
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session_id,
            "update": update.model_dump(mode="json", by_alias=True, exclude_none=True),
        }}), flush=True)
        return True


async def produce(wire_root: Path, project: Path):
    async with turn_source(wire_root, project, SESSION) as producer:
        name = producer.sessions.require(SESSION)
        async with AsyncExitStack() as turns:
            retired_owner = await Coordination.run_worker(partial(
                producer.turns.acquire_turn, turns, SESSION, name, TurnId("5e7a1d0c3b2f4e6a8c9d0b1a2f3e4d5c"), "Authored protocol; no input"))
            retired_lease = retired_owner.turn_lease
        retired = await Coordination.run_worker(partial(producer.turns.current_turn_update, SESSION))
        producer.on_connect(Pipe())
        consumer = AcpEventConsumer(producer, SESSION, producer._runtime)
        async with AsyncExitStack() as turns:
            await Coordination.run_worker(partial(
                producer.turns.acquire_turn, turns, SESSION, name, TurnId("a1c2e3f4b5d6e7f8091a2b3c4d5e6f70"), "Authored protocol; no input"))
            await producer.turns.publish_turn_state(consumer)
            await consumer.dispatch(agent_events.CompactionStart())
            await consumer.dispatch(agent_events.CompactionEnd(
                summary="Authored phase observation; not a native committed summary"))
            before = await Coordination.run_worker(partial(producer.turns.current_turn_update, SESSION))
            await Coordination.run_worker(partial(producer._comms.agents.finish_turn, retired_lease))
            assert await Coordination.run_worker(partial(producer.turns.current_turn_update, SESSION)) == before
            # An earlier finished cut: the current binding must refuse it.
            await consumer.dispatch(retired)
        await producer.turns.goals.sync_goal_execution(SESSION, name)


if __name__ == "__main__":
    asyncio.run(produce(Path(sys.argv[1]), Path(sys.argv[2])))
