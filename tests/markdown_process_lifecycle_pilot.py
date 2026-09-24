"""Process parsing discards obsolete documents and cannot hold widget teardown."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from runtime_fixture import ToadApp
from textual.widgets._markdown import MarkdownFence
from toad.widgets.agent_response import AgentResponse
from toad.render_tasks import execute_render_task


class ControlledPool:
    def __init__(self):
        self.requests = []

    async def run(self, function, *args):
        future = asyncio.get_running_loop().create_future()
        self.requests.append((function, args, future))
        await asyncio.wait((future,))
        return future.result()

    async def submit(self, task):
        return await self.run(execute_render_task, task)

    def complete(self, index):
        function, args, future = self.requests[index]
        future.set_result(function(*args))

    async def aclose(self):
        pass


async def wait_requests(pool, count, pilot):
    async with asyncio.timeout(5):
        while len(pool.requests) < count:
            await pilot.pause()


async def update(widget, text):
    await widget.update(text)


async def append(widget, text):
    await widget.append(text)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-markdown-lifecycle-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        pool = ControlledPool()
        with patch.object(app, "render_processes", pool):
            async with app.run_test(size=(110, 35)) as pilot:
                await pilot.pause()
                response = await app.screen.conversation.post(AgentResponse(paginate=False))
                source = "```python\nvalue = 123\n```\n"
                pending = asyncio.create_task(update(response, source))
                await wait_requests(pool, 1, pilot)
                app.theme = "ansi-light"
                await pilot.pause()
                pool.complete(0)
                await wait_requests(pool, 2, pilot)
                assert not response.query(MarkdownFence)
                pool.complete(1)
                await asyncio.wait_for(pending, 5)
                await pilot.pause()
                assert response.query_one(MarkdownFence)._highlighted_key[-2:] == (True, False)

                obsolete = asyncio.create_task(update(response, "```python\nobsolete = 1\n```"))
                await wait_requests(pool, 3, pilot)
                latest_source = "```python\nlatest = 2\n```"
                latest = asyncio.create_task(update(response, latest_source))
                await pilot.pause()
                pool.complete(2)
                await wait_requests(pool, 4, pilot)
                assert response.query_one(MarkdownFence).code == "value = 123"
                pool.complete(3)
                await asyncio.wait_for(asyncio.gather(obsolete, latest), 5)
                await pilot.pause()
                assert response.query_one(MarkdownFence).code == "latest = 2"

                # A superseded full update followed by append must not reuse
                # parse offsets from the previously rendered document.
                partial = "```python\ncomplete = "
                first = asyncio.create_task(update(response, partial))
                await wait_requests(pool, 5, pilot)
                second = asyncio.create_task(append(response, "3\n```"))
                await pilot.pause()
                pool.complete(4)
                await wait_requests(pool, 6, pilot)
                pool.complete(5)
                await asyncio.wait_for(asyncio.gather(first, second), 5)
                await pilot.pause()
                assert response.source == partial + "3\n```"
                assert response.query_one(MarkdownFence).code == "complete = 3"

                retiring = asyncio.create_task(update(response, "```python\nretired = 4\n```"))
                await wait_requests(pool, 7, pilot)
                await asyncio.wait_for(response.remove(), 2)
                await asyncio.wait_for(retiring, 2)
                pool.complete(6)
                await pilot.pause()
                assert not response.is_attached and not response._prepared_fences
                assert app._exception is None
    print("Markdown process lifecycle: theme, latest-source, append-after-supersession and cancellation-safe removal")


if __name__ == "__main__":
    asyncio.run(main())
