"""A pending history page may finish after its Window has been unmounted."""

import asyncio
import os
from pathlib import Path
import tempfile

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage
from committed_history_pilot import SnapshotAgent
from runtime_fixture import ToadApp


class DelayedSnapshotAgent(SnapshotAgent):
    def __init__(self, page):
        super().__init__(page)
        self.ready = True
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def get_transcript_page(self, **kwargs):
        self.entered.set()
        await self.release.wait()
        return self.page


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-transcript-teardown-", dir="/var/tmp") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 34)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            cursor = TranscriptCursor("", 0)
            page = TranscriptPage((TranscriptEvent("assistant", "Saved answer"),),
                                  cursor, cursor, False, False)
            agent = DelayedSnapshotAgent(page)
            view.set_reactive(type(view).agent, agent)
            view.agent_ready = True
            view._transcript_dirty = view._needs_transcript_checkpoint = True
            view.window.anchor()
            worker = view._compact_committed_history()
            await asyncio.wait_for(agent.entered.wait(), timeout=5)
            # Descendants disappear before Conversation itself during teardown.
            await view.window.remove()
            assert view.is_attached
            agent.release.set()
            await worker.wait()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("transcript teardown: late page safely discarded after Window removal")


if __name__ == "__main__":
    asyncio.run(main())
