"""Installed worker/ACP result contracts and declared reuse; no model inputs."""

import asyncio
import json
import multiprocessing
import os
from io import StringIO
from pathlib import Path
import sys
from time import perf_counter
from rich.console import Console
from rich.style import Style

from agent_comms.transcript_events import AssistantTranscript
from toad.acp.agent_controller import ApplicationValidationOwner, HeadlessValidationOwner
from toad.acp.sdk_boundary import (
    AcceptedSessionUpdateValidation, RejectedSessionUpdateValidation, ValidateSessionUpdateTask,
)
from toad.render_processes import RenderProcessPool
from toad.render_service import RenderServiceConfig
from toad.render_tasks import MarkdownRenderTask, RichRenderTask
from toad.rich_preparation import RichPresentation, SyntaxSource
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
    persistent_runtime = PreparationRuntime(persistent)
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

        # Both actual transports carry worker-owned token/strip representations.
        # Foreground delivery still gives each consumer its own native resources.
        console = Console(file=StringIO(), width=72, color_system="truecolor")
        rich_task = RichRenderTask(
            SyntaxSource("def captured_界():\n    return 'café'\n", "capture.py",
                         lexer="python", line_numbers=False),
            RichPresentation(console.options, Style(), None, False, None, "truecolor"),
        )
        markdown = MarkdownRenderTask("# CAPTURED_MARKDOWN\n\n```python\nvalue = '界'\n```\n", False, True)
        for name, shared in (("local", runtime), ("persistent", persistent_runtime)):
            renderer = PreparedRenderer(shared)
            first, second = await asyncio.gather(renderer.submit(markdown), renderer.submit(markdown))
            assert first.tokens is not second.tokens and first.fences is not second.fences
            assert "CAPTURED_MARKDOWN" in "".join(token.content for token in second.tokens)
            first.tokens[0].content = "one consumer changed"
            assert first.tokens[0].content != second.tokens[0].content
            first_rich, second_rich = await asyncio.gather(renderer.submit(rich_task), renderer.submit(rich_task))
            assert first_rich.lines is not second_rich.lines
            assert first_rich.lines[0] is not second_rich.lines[0]
            assert "captured_界" in second_rich.text and "café" in second_rich.text
            assert shared.retained_bytes <= shared.max_bytes
            receipt[name + "_captured_markdown_rich_independent_delivery"] = True
    finally:
        await runtime.aclose()
        await persistent_runtime.aclose()
        assert await persistent.shutdown_service()
    assert not local._pending and not persistent._pending and not runtime._pending
    assert {child.pid for child in multiprocessing.active_children()} == children_before
    receipt.update(elapsed=perf_counter() - started, cleanup=[], state="PASS",
                   scope="Actual installed local spawn, persistent ZMQ worker, official SDK and headless/application validation. No terminal pixels or provider turn.")
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).resolve()))
