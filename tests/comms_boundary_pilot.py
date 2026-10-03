"""Actual producer snapshots into mounted installed Toad, no provider/mock codecs."""

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agent_comms.acp import CommsAgent
from agent_comms.acp_extension import (
    AgentCommsUpdate,
    InputFailedUpdate,
    QueueChangedUpdate,
    decode_updates,
    encode_updates,
)
from agent_comms.acp_failure import ACPFailure
from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import Comms
from agent_comms.input_drain import QueuedInput
from agent_comms.mro_dispatch import handles
from agent_comms.threads import Thread
from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.acp.comms_updates import CommsUpdateConsumer
from toad.widgets.user_input import UserInput


@dataclass(frozen=True)
class PilotObservedUpdate(AgentCommsUpdate):
    observation: str


class PilotConsumer(CommsUpdateConsumer):
    @handles(PilotObservedUpdate)
    def observed(self, update):
        self.agent.observed_fact = update


class PilotAgent(Agent):
    comms_consumer_class = PilotConsumer


async def main():
    with tempfile.TemporaryDirectory(
        prefix="t2-boundary-", dir="/var/tmp"
    ) as directory:
        base = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(base / "wire"),
            XDG_CONFIG_HOME=str(base / "config"),
            XDG_STATE_HOME=str(base / "state"),
            XDG_DATA_HOME=str(base / "data"),
        )
        comms = Comms(base / "wire")
        comms.messaging.initialize_private_initial_protocol()
        comms.registry.register(
            Thread(
                "pilot",
                frozenset(),
                str(base),
                process_identity=ProcessIdentity.capture(os.getpid()),
            )
        )
        producer = CommsAgent(comms, auto_wake=False)
        producer.sessions.bindings["pilot"] = "pilot"
        producer.sessions.worktrees["pilot"] = str(base)
        owner, generation = comms.registry.live_owner_with_admission("pilot")
        producer.inputs.queued_inputs["pilot"] = {
            "a" * 32: QueuedInput("same text", True, owner.created_at, generation),
            "b" * 32: QueuedInput("same text", True, owner.created_at, generation),
        }
        notifications = []

        class Pipe:
            async def session_update(self, session_id, update):
                notifications.append(
                    json.loads(update.model_dump_json(by_alias=True, exclude_none=True))
                )

        pipe = Pipe()
        app = ToadApp(project_dir=str(base))
        try:
            async with app.run_test(size=(100, 34)) as pilot:
                await pilot.pause()
                view = app.selected_session.conversation
                agent = PilotAgent(
                    base,
                    {
                        "name": "T2",
                        "identity": "t2",
                        "short_name": "t2",
                        "run_command": {"*": "true"},
                        "protocol": "acp",
                    },
                    "pilot",
                )
                view.bind_agent(agent)
                view.agent = agent
                view.prompt.text = "preserved draft"
                cursor_token = agent._private_cursor.begin("pilot")
                queue_token = agent.queue_attachment.begin("pilot")
                response = {
                    "_meta": producer.sessions.metadata("pilot", session_id="pilot")
                }
                agent._receive_comms_response(response, cursor_token, queue_token)
                await pilot.pause()
                assert len(view.submissions.queue_projection.items) == 2
                assert [row.text for row in view.submissions.queued_inputs] == ["same text", "same text"]
                assert app.screen.coordination_root == str(comms.root)
                assert agent.coordination is app.coordination_facts[app.screen]

                async def deliver(update, session="pilot"):
                    await agent.server.call(
                        {
                            "jsonrpc": "2.0",
                            "method": "session/update",
                            "params": {"sessionId": session, "update": update},
                        }
                    )
                    await pilot.pause()

                item = producer.inputs.queued_inputs["pilot"].pop("a" * 32)
                await producer.inputs.emit_input_started(
                    "pilot", item.text, "a" * 32, queued_item=item, client=pipe
                )
                await producer.inputs.emit_queue_state("pilot", client=pipe)
                for update in notifications:
                    await deliver(update)
                assert len(view.submissions.queue_projection.items) == 1
                assert view.submissions.queue_projection.items[0].input_id == "b" * 32
                count = len(view.query(UserInput))
                for update in notifications:
                    await deliver(update)
                assert len(view.query(UserInput)) == count, (
                    "Started callback echoed twice"
                )
                assert view.prompt.text == "preserved draft"
                fact = PilotObservedUpdate("new case reached consumer")
                await deliver(
                    {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": ""},
                        "_meta": encode_updates(fact),
                    }
                )
                assert agent.observed_fact == fact
                # Same valid facts from a foreign ACP attachment cannot alter this owner.
                previous = agent.coordination
                await deliver(
                    {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": ""},
                        "_meta": response["_meta"],
                    },
                    "foreign",
                )
                assert agent.coordination == previous
                failure = ACPFailure.from_error(
                    -32603,
                    "Internal error",
                    {
                        "details": "Selected summary failed: Codex error: The usage limit has been reached (outcome uncertain; input not retried)"
                    },
                )
                await deliver(
                    {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": ""},
                        "_meta": encode_updates(InputFailedUpdate("unsent", failure)),
                    }
                )
                assert view.prompt.text == "preserved draft", (
                    "Failure replayed/restored server-owned input"
                )
                comms.registry.register(owner, new_owner=True)
                replacement = producer.inputs.queue_state("pilot")
                old = next(
                    value
                    for value in decode_updates(response["_meta"])
                    if isinstance(value, QueueChangedUpdate)
                )
                agent.queue_attachment.callback(replacement, "pilot")
                assert agent.queue_attachment.quarantined
                token = agent.queue_attachment.begin("pilot")
                agent.queue_attachment.bind(old, "pilot", token)
                assert agent.queue_attachment.quarantined, (
                    "Old generation regained queue authority"
                )
                token = agent.queue_attachment.begin("pilot")
                agent.queue_attachment.bind(replacement, "pilot", token)
                assert not agent.queue_attachment.quarantined
                assert not agent.queue_attachment.projection.items
                assert app._exception is None
        finally:
            await producer.shutdown()
    print(
        "Mounted current producer queue/cursor/coordination/new-case/error boundaries passed; exact IDs, generation fences, no replay"
    )


if __name__ == "__main__":
    asyncio.run(main())
