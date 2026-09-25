"""Run actual Toad rendering through the persistent typed ZMQ backend."""

import asyncio
import os
from pathlib import Path
import tempfile

from runtime_fixture import ToadApp
from tool_diff_fixture import wait_for_tool_diff
from textual.widgets._markdown import MarkdownFence
from textual.worker import Worker, WorkerState
from toad.render_runtime import PersistentRenderer
from toad.render_service import RenderServiceConfig
from toad.render_zmq import PersistentRendererPool
from toad.widgets.agent_response import AgentResponse
from toad.widgets.tool_call import ToolCall
from toad.widgets.project_panel import FilePreview
from toad.widgets.worker_static import WorkerStatic
from textual.selection import SELECT_ALL

PATCH = "--- x.py\n+++ x.py\n@@ -1,2 +1,2 @@\n context\n-old = 1\n+new = 2\n"


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-persistent-ui-") as directory:
        root = Path(directory)
        config = RenderServiceConfig(max_workers=2, max_pending=4)
        identities = []
        renderer: PersistentRenderer | None = None
        pool: PersistentRendererPool | None = None
        try:
            for index in range(2):
                current = root / f"client-{index}"
                current.mkdir()
                os.environ.update(AGENT_COMMS_ROOT=str(current / "wire"), XDG_CONFIG_HOME=str(current / "config"),
                                  XDG_STATE_HOME=str(current / "state"), XDG_DATA_HOME=str(current / "data"))
                renderer = PersistentRenderer(root / "renderer", config)
                assert renderer.resolved_pool is None
                app = ToadApp(project_dir=str(current), renderer=renderer)
                warmed = asyncio.Event()
                warm_states = []

                def observe_warmup(message):
                    if (isinstance(message, Worker.StateChanged) and message.worker.group == "renderer-warmup"
                            and message.state in {WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED}):
                        warm_states.append(message.state)
                        warmed.set()

                async with app.run_test(size=(110, 35), message_hook=observe_warmup) as pilot:
                    await asyncio.wait_for(warmed.wait(), 10)
                    assert warm_states == [WorkerState.SUCCESS], warm_states
                    await pilot.pause()
                    source = "```python\n" + "value = 123\n" * 100 + "```\n"
                    response = await app.screen.conversation.post(AgentResponse(paginate=False))
                    await response.update(source)
                    await pilot.pause()
                    assert response.query_one(MarkdownFence).code.startswith("value = 123")
                    tool = await app.screen.conversation.post(ToolCall({
                        "toolCallId": "persistent", "kind": "edit", "title": "Synthetic edit",
                        "status": "completed", "content": [{"type": "content", "content": {
                            "type": "resource", "resource": {"mimeType": "text/x-diff", "text": PATCH},
                        }}],
                    }))
                    tool.set_expanded(True)
                    diff = await wait_for_tool_diff(tool, pilot)
                    assert diff.patch == PATCH
                    path = current / "persistent-preview.py"
                    path.write_text(f"PERSISTENT_PREVIEW_{index} = 42\n")
                    await app.open_file_preview(path)
                    preview = app.screen.query_one(FilePreview)
                    await asyncio.wait_for(preview.wait_ready(), 20)
                    content = preview.query_one(WorkerStatic)
                    assert content._prepared is not None
                    assert f"PERSISTENT_PREVIEW_{index}" in "\n".join(line.text for line in content._prepared.lines)
                    await app.close_session_mode(app.current_mode)
                    read_source = f"def persistent_read_{index}():\n    return 42\n\n"
                    read_tool = await app.screen.conversation.post(ToolCall({
                        "toolCallId": f"persistent-read-{index}", "kind": "read", "title": "Read module.py",
                        "status": "completed", "rawInput": {"path": "module.py"},
                        "content": [{"type": "content", "content": {"type": "text", "text": read_source}}],
                    }))
                    read_tool.set_expanded(True)
                    async with asyncio.timeout(10):
                        while not read_tool.query(WorkerStatic):
                            await pilot.pause(.01)
                    read_view = read_tool.query_one(WorkerStatic)
                    await asyncio.wait_for(read_view.wait_ready(), 10)
                    assert read_view.get_selection(SELECT_ALL)[0] == SELECT_ALL.extract(read_source)
                    assert app._exception is None
                    pool = renderer.resolved_pool
                    assert pool is not None
                    client = pool._connection.client
                    assert client is not None and client.connected_endpoint is not None
                    identities.append(client.connected_endpoint.process_identity)
                assert pool is not None and not pool._pending
            assert identities[0] == identities[1]
            print("persistent UI: two Toad instances reused one renderer; Markdown, native diff, file preview and Read tool completed")
        finally:
            if renderer is not None:
                pool = renderer.resolved_pool or pool
                await renderer.aclose()
            if pool is not None:
                assert await pool.shutdown_service()
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
