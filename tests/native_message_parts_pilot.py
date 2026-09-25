"""One saved native assistant message keeps its Markdown and one timestamp."""

import asyncio
import json
import os
from pathlib import Path
import tempfile

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from textual.widgets._markdown import MarkdownBulletList, MarkdownFence
from toad.acp.agent import Agent
from toad.widgets.agent_response import AgentResponse
from toad.widgets.message_divider import MessageDivider


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-native-message-parts-", dir="/var/tmp") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        parts = ["## Plan\n\n", "- **Read** first\n", "- Keep working\n\n",
                 "```python\n", "value = 123\n", "```\n"]
        session = root / "native.jsonl"
        session.write_text(json.dumps({"type": "message", "id": "native-message", "message": {
            "role": "assistant", "content": [{"type": "text", "text": part} for part in parts],
        }}) + "\n")
        comms = wire(root / "wire")
        comms.register(Thread("worker", frozenset(), str(root), session_file=str(session)))
        saved = comms.thread_transcript_page("worker")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 38)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(root, {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
                                 "run_command": {"*": "true"}, "protocol": "acp"}, "fixture")
            agent._message_target = view
            agent.rpc_session_update("fixture", {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": ""},
                "_meta": {"agentComms": {"transcript": [event.to_wire() for event in saved.events]}},
            })
            await pilot.pause()
            assert len(view.contents.query(MessageDivider)) == 1, "one native row gained extra timestamps"
            body = view.contents.query_one(AgentResponse)
            assert body.source == "".join(parts)
            async with asyncio.timeout(5):
                while not body.query(MarkdownFence):
                    await pilot.pause(.02)
            assert body.query_one(MarkdownFence).code == "value = 123"
            assert body.query(MarkdownBulletList)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("native assistant parts: one timestamp, exact combined Markdown, list and code fence retained")


if __name__ == "__main__":
    asyncio.run(main())
