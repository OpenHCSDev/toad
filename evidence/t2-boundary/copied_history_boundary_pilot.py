"""Installed shared extension mounts copied converted native history without a send."""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from agent_comms.acp_extension import TranscriptSnapshotUpdate, encode_updates
from agent_comms.comms import Comms
from comms_boundary_fixture import coordination_fact
from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    copied = Path(os.environ["T2_COPIED_HISTORY_ROOT"]).resolve()
    comms = Comms(copied)
    thread = comms.registry.require("agent-comms-ux")
    session = Path(thread.session_file)
    assert session.is_relative_to(copied)
    before = session.stat()
    page = comms.transcripts.thread_transcript_page(thread.name)
    assert page.events and page.has_older
    fact = TranscriptSnapshotUpdate(page)
    encoded = encode_updates(fact)
    with tempfile.TemporaryDirectory(
        prefix="t2-copied-history-", dir="/var/tmp"
    ) as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "ui-wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(
                root,
                {
                    "name": "Copied history",
                    "identity": "history",
                    "run_command": {"*": "true"},
                    "protocol": "acp",
                },
                thread.name,
            )
            agent._message_target = view
            view.agent = agent
            agent.comms_consumer_class(agent, thread.name).dispatch_sync(
                coordination_fact(thread.name, str(copied))
            )
            await agent.server.call(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": thread.name,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": ""},
                            "_meta": encoded,
                        },
                    },
                }
            )
            async with asyncio.timeout(20):
                while not view.contents.query(TranscriptHistory):
                    await pilot.pause(0.05)
            history = view.contents.query_one(TranscriptHistory)
            assert history.pages[-1].page.after == page.after
            assert history.has_older
            assert app.screen.viewport_presentation.windows
            assert app._exception is None
    after = session.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    print(
        json.dumps(
            {
                "installed_copied_native_history": "passed",
                "session_bytes": before.st_size,
                "events": len(page.events),
                "older_history": page.has_older,
                "sends": 0,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
