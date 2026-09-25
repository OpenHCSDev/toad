"""Only owner-identified context is collapsed; its Markdown remains inspectable."""

import asyncio
import os
from pathlib import Path
import tempfile

from agent_comms import TranscriptEvent
from runtime_fixture import ToadApp
from textual.widgets import Collapsible
from textual.widgets._markdown import MarkdownBulletList, MarkdownFence, MarkdownParagraph
from toad.acp.agent import Agent
from toad.widgets.agent_response import AgentResponse
from toad.widgets.message_divider import MessageDivider
from toad.widgets.transcript_fragments import transcript_fragments
from toad.widgets.user_input import UserInput


CONTEXT = ("Coordination context: **owner identity**\n\n"
           "- First instruction\n- Second instruction\n\n"
           "```python\nvalue = 123\n```\n")


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-owner-context-", dir="/var/tmp") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        # One collapsed disclosure even when its source is larger than the page budget.
        large = transcript_fragments((TranscriptEvent("context", CONTEXT * 20),))
        assert len(large) == 1 and large[0].events[0].text == CONTEXT * 20
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 38)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(root, {"name": "Fixture", "identity": "fixture",
                                 "short_name": "fixture", "run_command": {"*": "true"},
                                 "protocol": "acp"}, "fixture")
            agent._message_target = view
            agent.rpc_session_update("fixture", {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": ""},
                "_meta": {"agentComms": {"transcript": [
                    TranscriptEvent("context", CONTEXT).to_wire(),
                    TranscriptEvent("user", CONTEXT).to_wire(),
                ]}},
            })
            await pilot.pause()
            disclosure = view.contents.query_one(Collapsible)
            assert disclosure.collapsed
            assert disclosure.title == "Agent coordination context"
            assert not disclosure.query(AgentResponse), "Hidden context must not parse Markdown eagerly"
            assert not disclosure.query(MessageDivider), "Context is not a new User message"
            assert view.contents.query_one(UserInput).content == CONTEXT
            disclosure.collapsed = False
            await pilot.pause()
            body = disclosure.query_one(AgentResponse)
            async with asyncio.timeout(5):
                while not body.query(MarkdownFence):
                    await pilot.pause(.02)
            assert body.source == CONTEXT
            assert body.query_one(MarkdownFence).code == "value = 123"
            assert body.query(MarkdownBulletList)
            assert any(span.style == ".strong"
                       for paragraph in body.query(MarkdownParagraph)
                       for span in paragraph._content.spans)
            disclosure.collapsed = True
            await pilot.pause()
            disclosure.collapsed = False
            await pilot.pause()
            assert len(disclosure.query(AgentResponse)) == 1
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("owner context: collapsed and lazy, full Markdown on expansion, literal user quotes preserved")


if __name__ == "__main__":
    asyncio.run(main())
