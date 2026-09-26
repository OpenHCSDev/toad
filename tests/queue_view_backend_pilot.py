"""Real pinned ACP producer -> real Agent -> mounted Prompt, no provider/process.

Only transport and native event generation are fixtures. Durable dispositions,
ACP admission/new/load, alias translation, queue emission and UI reduction are
production paths. Synthetic input_started is not a native consumption receipt.
"""

from __future__ import annotations

import asyncio
import inspect
import os
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from agent_comms import backend
from agent_comms.acp import CommsAgent
from agent_comms.declarations import Thread
from agent_comms.operations import Comms
from agent_comms.runtime import _present_cursor_session
from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.widgets.prompt import QueueSummary
from toad.widgets.user_input import UserInput

AGENT = {
    "name": "Queue fixture",
    "identity": "queue-fixture",
    "short_name": "fixture",
    "run_command": {"*": "true"},
    "protocol": "acp",
}


async def main():
    expected = {
        CommsAgent: "53b854ad9b7e3367218e4b5b27b18a89ce1a48e06a72f5b75334a6f6759d12d9",
        _present_cursor_session: "af212a2f8aaa9d0e90fcc23ec0f7f4a1fbf7c1b88ed11fd1ca923e45bf040267",
    }
    for obj, digest in expected.items():
        source = Path(inspect.getfile(obj))
        assert sha256(source.read_bytes()).hexdigest() == digest
        # Multiple producer commits may share these bytes. Record import paths;
        # the invoking archive manifest supplies the exact whole-repo revision.
        print(f"SOURCE {source}: {digest}", flush=True)
    with TemporaryDirectory(prefix="toad-queue-backend-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            AGENT_COMMS_ROOT=str(root / "wire"),
            AGENT_COMMS_AGENT_MODELS="test/base",
        )
        comms = Comms(root / "wire")
        comms.register(Thread("alias", frozenset(), str(root), pid=os.getpid()))
        comms.registry.rename("alias", "beta")
        producer = CommsAgent(
            comms, agent_bin="pi", agent_args=["--model", "test/base"], auto_wake=False
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(125, 42)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            consumer = Agent(root, AGENT, "beta")
            consumer._message_target = view
            view.agent = consumer
            summary = view.query_one(QueueSummary)
            receipts, callbacks = [], []
            active, release_start, started, finish = (asyncio.Event() for _ in range(4))

            def presented(result):
                value = result.model_dump(by_alias=True, exclude_none=False)
                if consumer.session_id == "alias":
                    _present_cursor_session(value.get("_meta"), "alias")
                return value

            class Client:
                async def session_update(self, *, session_id, update):
                    value = presented(update)
                    callbacks.append(deepcopy(value))
                    consumer.rpc_session_update(
                        consumer.session_id or session_id, value
                    )

            producer.on_connect(Client())

            async def delivery(*, include_history=False):
                return comms.input_delivery(
                    "beta",
                    include_history=include_history,
                    awaiting_keys=producer.awaiting_input_keys("beta"),
                )

            consumer.get_input_delivery = delivery

            class Request:
                def __init__(self, callback):
                    self.callback = callback

                async def wait(self):
                    return presented(await self.callback())

            def new(*args, **kwargs):
                return Request(lambda: producer.new_session(str(root)))

            def load(*args, **kwargs):
                # Owner-side canonical load, followed by the actual owner proxy
                # alias mapper, exactly as its trusted ready metadata is framed.
                return Request(lambda: producer.load_session(str(root), "beta"))

            def prompt(blocks, session, metadata):
                assert session in ("beta", "alias")

                async def invoke():
                    result = await producer.prompt("beta", blocks, field_meta=metadata)
                    receipts.append(result)
                    return result

                return Request(invoke)

            async def native_events(*args, **kwargs):
                active.set()
                yield {"type": "chunk", "text": "Provider-free original response"}
                await release_start.wait()
                first = await kwargs["steering_queue"].get()
                yield {"type": "input_started", "id": first["_input_id"]}
                started.set()
                await finish.wait()
                yield {"type": "done", "ok": True}

            def painted(text, artifact):
                assert text in summary.render().plain, summary.render().plain
                assert summary in app.screen._compositor.visible_widgets
                frame = "\n".join(
                    strip.text for strip in app.screen._compositor.render_strips()
                )
                assert text in frame, frame
                if output := os.environ.get("QUEUE_EVIDENCE_DIR"):
                    Path(output).mkdir(parents=True, exist_ok=True)
                    (Path(output) / f"{artifact}.svg").write_text(
                        app.export_screenshot()
                    )

            with (
                patch.object(
                    producer,
                    "_declare_thread",
                    return_value=comms.registry.require("beta"),
                ),
                patch.object(producer, "_ensure_live_drain"),
                patch.object(
                    producer, "_config_options", new=AsyncMock(return_value=[])
                ),
                patch("toad.acp.agent.api.session_new", side_effect=new),
                patch("toad.acp.agent.api.session_load", side_effect=load),
                patch("toad.acp.agent.api.session_prompt", side_effect=prompt),
                patch.object(backend, "stream_agent_events", native_events),
            ):
                await consumer.acp_new_session()
                await pilot.pause()
                assert (
                    view.queue_supported
                    and consumer._queue_view.scope.owner_thread == "beta"
                )
                view.prompt.text = "local editable draft"
                turn = asyncio.create_task(
                    consumer.send_prompt("initial fixture prompt")
                )
                try:
                    await asyncio.wait_for(active.wait(), 5)
                    await consumer.send_prompt("same text", defer_display=True)
                    await consumer.send_prompt("same text", defer_display=True)
                    await pilot.pause()
                    ids = tuple(producer._queued_inputs["beta"])
                    assert len(ids) == 2 and ids[0] != ids[1]
                    assert (
                        tuple(row.input_id for row in view.queue_projection.items)
                        == ids
                    )
                    assert all(
                        producer._dispositions.get("acp:" + exact)["status"]
                        == "unknown"
                        for exact in ids
                    )
                    assert len(view.input_delivery["inputs"]) >= 2
                    painted("Queued (2): same text", "backend-queued-two")
                    before = len(view.query(UserInput))
                    release_start.set()
                    await asyncio.wait_for(started.wait(), 5)
                    await pilot.pause()
                    assert tuple(
                        row.input_id for row in view.queue_projection.items
                    ) == (ids[1],)
                    assert len(view.query(UserInput)) == before + 1
                    painted("Queued (1): same text", "backend-exact-start")
                    # Duplicate/reordered real emitted packets do not echo again.
                    start_packet = next(
                        packet
                        for packet in callbacks
                        if "inputStarted"
                        in (packet.get("_meta") or {}).get("agentComms", {})
                    )
                    consumer.rpc_session_update("beta", deepcopy(start_packet))
                    await pilot.pause()
                    assert len(view.query(UserInput)) == before + 1
                    finish.set()
                    await asyncio.wait_for(turn, 5)
                    await pilot.pause()
                    assert not view.queue_projection.items
                    assert tuple(
                        row.input_id for row in view.queue_projection.restored
                    ) == (ids[1],)
                    assert (
                        producer._dispositions.get("acp:" + ids[1])["status"]
                        == "unknown"
                    )
                    assert view.prompt.text == "local editable draft"
                    painted("Restored (1, read-only): same text", "backend-restored")
                    consumer.session_id = "alias"
                    await consumer.acp_load_session()
                    await pilot.pause()
                    assert consumer._queue_view.scope.session_id == "alias"
                    assert consumer._queue_view.scope.owner_thread == "beta"
                    assert tuple(
                        row.input_id for row in view.queue_projection.restored
                    ) == (ids[1],)
                    painted("Restored (1, read-only): same text", "backend-alias-load")
                    # Actual ACP invalid UTF-8 ingress: exact admission persists,
                    # trusted load is attachable but projection is null.
                    producer._active_turns["beta"] = "fixture-held"
                    inbox = producer._backend_inboxes["beta"] = asyncio.Queue()
                    response = await producer.prompt(
                        "beta",
                        [{"type": "text", "text": "valid model task"}],
                        agentComms={
                            "delivery": "queue",
                            "deferDisplay": True,
                            "userText": "\ud800",
                        },
                    )
                    invalid_id = inbox.get_nowait()["_input_id"]
                    assert (
                        response.field_meta["agentComms"]["inputDisposition"]["inputId"]
                        == invalid_id
                    )
                    await consumer.acp_load_session()
                    await pilot.pause()
                    assert view.queue_projection.status == "unavailable"
                    assert invalid_id in producer._queued_inputs["beta"]
                    assert (
                        producer._dispositions.get("acp:" + invalid_id)["status"]
                        == "unknown"
                    )
                    assert view.prompt.text == "local editable draft"
                    painted("Remote queue unavailable", "backend-surrogate-null")
                    # Rebase hides old-admission rows but cannot delete their
                    # durable UNKNOWN or infer their native consumption.
                    owner = comms.registry.require("beta")
                    comms.registry.register(owner, new_owner=True)
                    await producer._emit_queue_state("beta")
                    await pilot.pause()
                    consumer.rpc_session_update(
                        "alias",
                        {"sessionUpdate": "config_option_update", "configOptions": []},
                    )
                    await pilot.pause()
                    assert view.queue_projection.status == "unavailable"
                    await consumer.acp_load_session()
                    await pilot.pause()
                    assert view.queue_projection.status == "available"
                    assert (
                        not view.queue_projection.items
                        and not view.queue_projection.restored
                    )
                    assert invalid_id in producer._queued_inputs["beta"]
                    assert ids[1] in producer._restored_inputs["beta"]
                    assert (
                        producer._dispositions.get("acp:" + invalid_id)["status"]
                        == "unknown"
                    )
                    assert (
                        producer._dispositions.get("acp:" + ids[1])["status"]
                        == "unknown"
                    )
                    assert view.prompt.text == "local editable draft"
                finally:
                    finish.set()
                    if not turn.done():
                        turn.cancel()
                    await asyncio.gather(turn, return_exceptions=True)
                    producer._active_turns.pop("beta", None)
                    await producer.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
    print(
        "PASS: verified ACP/runtime bytes; real ACP admission/new/load/start/restore/alias/surrogate-null/rebase -> mounted queue; UNKNOWN/draft preserved; cleanup completed"
    )
