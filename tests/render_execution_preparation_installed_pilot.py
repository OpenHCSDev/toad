"""Installed worker/ACP result contracts and declared reuse; no model inputs."""

import asyncio
import json
import multiprocessing
import os
from pathlib import Path
import sys
from time import perf_counter

from agent_comms.transcript_events import AssistantTranscript
from toad.acp.agent_controller import ApplicationValidationOwner, HeadlessValidationOwner
from toad.acp.sdk_boundary import (
    AcceptedSessionUpdateValidation, RejectedSessionUpdateValidation, ValidateSessionUpdateTask,
)
from toad.render_processes import RenderProcessPool
from toad.render_service import RenderServiceConfig
from toad.widgets.transcript_fragments import TranscriptRenderTask
from toad.render_zmq import PersistentRendererPool, RendererEndpoint
from toad.work_preparation import PreparationRuntime, PreparedRenderer, RenderPreparation


async def main(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    children_before = {child.pid for child in multiprocessing.active_children()}
    local = RenderProcessPool(max_workers=1, max_pending=2)
    runtime = PreparationRuntime(local)
    endpoint = await asyncio.to_thread(
        RendererEndpoint.for_runtime, output / "renderer", RenderServiceConfig(max_workers=1, max_pending=2),
    )
    persistent = PersistentRendererPool(endpoint, RenderServiceConfig(max_workers=1, max_pending=2))
    receipt = {"python": sys.executable, "provider_calls": 0, "public_inputs": 0}
    try:
        task = ValidateSessionUpdateTask("renderer-owner", {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "SDK_VALIDATION"},
        })
        invalid = ValidateSessionUpdateTask("renderer-owner", {"sessionUpdate": "unsupported_update"})
        for name, owner in (
            ("headless", HeadlessValidationOwner()),
            ("local", ApplicationValidationOwner(local)),
            ("persistent", ApplicationValidationOwner(persistent)),
        ):
            accepted = await owner.validate(task)
            assert isinstance(accepted, AcceptedSessionUpdateValidation)
            assert accepted.notification.update.content.text == "SDK_VALIDATION"
            assert isinstance(await owner.validate(invalid), RejectedSessionUpdateValidation)
            receipt[name + "_official_sdk_accepted_and_rejected"] = True
        try:
            await task.complete(asyncio.sleep(0, result="not an SDK result"))
        except TypeError:
            receipt["wrong_completed_result_refused"] = True
        else:
            raise AssertionError("Completed execution bypassed its task's result contract")

        # Non-reusable SDK captures keep distinct admission and no retained entry.
        first = await RenderPreparation(task).identity(runtime)
        second = await RenderPreparation(task).identity(runtime)
        assert first != second
        await runtime.submit(RenderPreparation(task))
        await runtime.submit(RenderPreparation(task))
        assert not runtime._ready
        receipt["non_reusable_capture_not_shared_or_retained"] = True

        prepared = PreparedRenderer(runtime)
        transcript = TranscriptRenderTask((AssistantTranscript("REUSABLE_RENDER_SOURCE"),))
        a, b = await asyncio.gather(prepared.submit(transcript), prepared.submit(transcript))
        assert a == b and a is not b
        assert await prepared.submit(transcript) == a
        assert runtime.hits + runtime.shared >= 2 and len(runtime._ready) == 1
        receipt["reusable_capture_shared_retained_and_independently_delivered"] = True
    finally:
        await runtime.aclose()
        await persistent.aclose()
        assert await persistent.shutdown_service()
    assert not local._pending and not persistent._pending and not runtime._pending
    assert {child.pid for child in multiprocessing.active_children()} == children_before
    receipt.update(elapsed=perf_counter() - started, cleanup=[], state="PASS",
                   scope="Actual installed local spawn, persistent ZMQ worker, official SDK and headless/application validation. No terminal pixels or provider turn.")
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).resolve()))
