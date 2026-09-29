"""Candidate ACP admission/emission -> mounted queue, with local transport.

The held backend and explicit input-start event are test fixtures. Actual ACP
admission, durable UNKNOWN, queue retirement and UI callbacks execute normally;
this check does not claim native provider consumption.
"""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms.acp import CommsAgent
from agent_comms.acp_extension import (
    InputDeliveryChangedUpdate,
    InputStartedUpdate,
    QueuePromptRequest,
    decode_updates,
    encode_request,
)
from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import Comms
from agent_comms.threads import Thread
from runtime_fixture import ToadApp

AGENT = {
    "name": "Queue",
    "identity": "queue",
    "run_command": {"*": "true"},
    "protocol": "acp",
}
from toad.acp.agent import Agent
from toad.widgets.prompt import QueueSummary
from toad.widgets.user_input import UserInput


async def main():
    with TemporaryDirectory(prefix="toad-queue-backend-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
        )
        comms = Comms(root / "wire")
        comms.messaging.initialize_private_initial_protocol()
        comms.threads.register(
            Thread(
                "beta",
                frozenset(),
                str(root),
                process_identity=ProcessIdentity.capture(os.getpid()),
            )
        )
        producer = CommsAgent(comms, auto_wake=False)
        producer.sessions.bindings["beta"] = "beta"
        producer.turns.active_turns["beta"] = "fixture-held"
        inbox = producer.inputs.backend_inboxes["beta"] = asyncio.Queue()
        app = ToadApp(project_dir=str(root))
        try:
            async with app.run_test(size=(160, 42)) as pilot:
                await pilot.pause()
                view = app.screen.conversation
                consumer = Agent(root, AGENT, "beta")
                consumer.attach_surface(view)
                view.agent = consumer
                callbacks = []

                class Client:
                    async def session_update(self, *, session_id, update):
                        packet = update.model_dump(by_alias=True, exclude_none=False)
                        callbacks.append(packet)
                        consumer.rpc_session_update(session_id, packet)

                producer.on_connect(Client())

                async def delivery(*, include_history=False):
                    return comms.goals.input_delivery(
                        "beta",
                        include_history=include_history,
                        awaiting_keys=producer.inputs.awaiting_input_keys("beta"),
                    )

                consumer.get_input_delivery = delivery

                class Response:
                    async def wait(self):
                        return {
                            "sessionId": "beta",
                            "_meta": producer.sessions.metadata(
                                "beta", session_id="beta"
                            ),
                        }

                async def load():
                    with patch(
                        "toad.acp.agent.api.session_load", return_value=Response()
                    ):
                        await consumer.acp_load_session()
                    await pilot.pause()

                async def enqueue(text):
                    response = await producer.prompt(
                        "beta",
                        [{"type": "text", "text": "local queued task"}],
                        field_meta=encode_request(QueuePromptRequest(text, True)),
                    )
                    await pilot.pause()
                    return next(
                        f.input_id
                        for f in decode_updates(response.field_meta)
                        if isinstance(f, InputDeliveryChangedUpdate)
                    )

                await load()
                view.prompt.text = "local editable draft"
                ids = [await enqueue("same text"), await enqueue("same text")]
                assert ids[0] != ids[1]
                assert [row.input_id for row in view.queue_projection.items] == ids
                assert all(
                    producer.inputs.dispositions.read().rows["acp:" + exact].unresolved
                    for exact in ids
                )
                summary = view.query_one(QueueSummary)
                assert summary in app.screen._compositor.visible_widgets
                assert "Queued (2)" in summary.render().plain
                before = len(view.query(UserInput))
                await producer.inputs.input_started("beta", ids[0], (), None)
                await pilot.pause()
                assert [row.input_id for row in view.queue_projection.items] == ids[1:]
                assert len(view.query(UserInput)) == before + 1
                started = next(
                    packet
                    for packet in callbacks
                    if any(
                        isinstance(f, InputStartedUpdate)
                        for f in decode_updates(packet["_meta"])
                    )
                )
                consumer.rpc_session_update("beta", started)
                await pilot.pause()
                assert len(view.query(UserInput)) == before + 1
                await producer.inputs.finish_turn_inputs("beta", inbox)
                await pilot.pause()
                assert [row.input_id for row in view.queue_projection.restored] == ids[
                    1:
                ]
                assert "Restored (1, read-only)" in summary.render().plain
                assert view.prompt.text == "local editable draft"
                assert (
                    producer.inputs.dispositions.read().rows["acp:" + ids[1]].unresolved
                )
                assert all(decode_updates(packet["_meta"]) for packet in callbacks)
                producer.inputs.backend_inboxes["beta"] = asyncio.Queue()
                invalid = await enqueue("\ud800")
                assert view.queue_projection.status == "unavailable"
                assert "Remote queue unavailable" in summary.render().plain
                assert (
                    producer.inputs.dispositions.read()
                    .rows["acp:" + invalid]
                    .unresolved
                )
                assert view.prompt.text == "local editable draft"
                comms.registry.register(comms.registry.require("beta"), new_owner=True)
                await load()
                assert view.queue_projection.status == "available"
                assert (
                    not view.queue_projection.items
                    and not view.queue_projection.restored
                )
                assert invalid in producer.inputs.queued_inputs["beta"]
                assert ids[1] in producer.inputs.restored_inputs["beta"]
                assert app._exception is None
                await consumer.stop()
        finally:
            producer.turns.active_turns.pop("beta", None)
            await producer.shutdown()
    print(
        "PASS: actual ACP queue admission/emission/retirement -> mounted UI; no retired keys; UNKNOWN, exact IDs and local draft retained"
    )


if __name__ == "__main__":
    asyncio.run(main())
