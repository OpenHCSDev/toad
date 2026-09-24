"""Appending output and toggling the sidebar must not restyle old transcript trees."""

import asyncio
import os
import tempfile
import time
from pathlib import Path

from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.side_bar import SideBar


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-style-work-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            response = AgentResponse("\n\n".join(f"## Heading {i}\n\nA paragraph." for i in range(80)))
            await app.screen.conversation.post(response)
            await pilot.pause()
            old = set(response.walk_children(with_self=True))
            original = app.stylesheet.apply
            styled = 0

            def apply(node, *args, **kwargs):
                nonlocal styled
                styled += node in old
                return original(node, *args, **kwargs)

            app.stylesheet.apply = apply
            start = time.perf_counter()
            await response.append("\n\n## New output\n\nAnother paragraph.")
            await pilot.pause()
            append_styled = styled
            append_ms = (time.perf_counter() - start) * 1000
            styled = 0
            start = time.perf_counter()
            app.screen.query_one(SideBar).toggle()
            await pilot.pause()
            print({"append_old_nodes_restyled": append_styled,
                   "sidebar_old_nodes_restyled": styled,
                   "append_ms": append_ms, "sidebar_ms": (time.perf_counter() - start) * 1000})
            assert append_styled == 0
            assert styled == 0


if __name__ == "__main__":
    asyncio.run(main())
