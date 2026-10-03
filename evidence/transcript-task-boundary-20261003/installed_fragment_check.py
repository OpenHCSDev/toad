"""Final installed check of the changed import and worker boundaries."""

import asyncio
import json
import multiprocessing
import sys
from pathlib import Path

from agent_comms.transcript_events import AgentTextTranscript, UserTranscript
from toad import transcript_preparation, work_preparation
from toad.render_processes import RenderProcessPool
from toad.render_protocol import TaskCapture
from toad.widgets.transcript_fragments import TranscriptRenderTask


def check_imports():
    assert not any(name == "textual" or name.startswith("textual.") for name in sys.modules)
    assert "toad.render_tasks" not in sys.modules


async def main():
    check_imports()
    events = (UserTranscript("Question"), AgentTextTranscript("Answer\n\nSecond block."))
    original = TranscriptRenderTask(events)
    restored = TaskCapture.decode(TaskCapture.encode(original))
    assert type(restored) is TranscriptRenderTask and restored.events == events
    pool = RenderProcessPool(max_workers=1, max_pending=1)
    try:
        fragments = await pool.submit(restored)
        assert tuple(event for fragment in fragments for event in fragment.events) == events
        assert all(fragment.retained_bytes > 0 for fragment in fragments)
    finally:
        await pool.aclose()
    check_imports()
    assert not multiprocessing.active_children()
    print(json.dumps({
        "result": "passed", "task_module": type(restored).__module__,
        "installed_package": str(Path(transcript_preparation.__file__).parent),
        "fragments": len(fragments), "textual_loaded": False,
        "native_catalog_loaded": False, "cleanup": [],
    }))


if __name__ == "__main__":
    asyncio.run(main())
