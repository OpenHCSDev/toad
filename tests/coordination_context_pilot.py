"""Only owner-identified context is collapsed; its Markdown remains inspectable."""

import asyncio
import json
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
from toad.widgets.coordination_context import CoordinationContext, OriginalCoordinationContext
from toad.coordination_context_format import format_coordination_context


CONTEXT = ("Coordination context: **owner identity**\n\n"
           "- First instruction\n- Second instruction\n\n"
           "```python\nvalue = 123\n```\n")


async def main():
    structured = json.dumps({"identity": {"thread": "owner"}, "rules": ["First", "Second"]})
    assert "**Identity:**" in format_coordination_context(structured)
    assert "**Thread:** owner" in format_coordination_context(structured)
    assert "- First" in format_coordination_context(structured)
    for unchanged in (CONTEXT, '{"thread":"first","thread":"second"}', "Peer state: [broken"):
        assert format_coordination_context(unchanged) == unchanged
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

            raw = ("Coordination context: you are thread 'owner'; parent=None. Keep the supplied instructions. "
                   "Peer state: " + json.dumps([
                       {"name": "peer-a", "status": "running", "activity": "working", "activity_detail": "Read | review"},
                       {"name": "peer-b", "status": "stopped", "activity": "idle", "activity_detail": "Done"},
                   ]) + "\n\nReview the changes.")
            readable = await view.post(CoordinationContext(raw))
            await pilot.pause()
            assert readable.collapsed and not readable.query(AgentResponse)
            readable.expand_block()
            async with asyncio.timeout(5):
                while not readable.query("MarkdownTable"):
                    await pilot.pause(.02)
            body = readable.query(AgentResponse).first()
            assert "## Peers" in body.source and "## Task context" in body.source
            assert "| Thread | Status | Activity | Details |" in body.source
            assert "Read \\| review" in body.source
            assert "Review the changes." in body.source
            assert readable.get_block_content("clipboard") == raw
            original = readable.query_one(OriginalCoordinationContext)
            assert original.collapsed and not original.query(AgentResponse)
            original.collapsed = False
            async with asyncio.timeout(5):
                while not original.query(MarkdownFence):
                    await pilot.pause(.02)
            assert original.query_one(MarkdownFence).code.rstrip("\n") == raw
            assert original.get_block_content("clipboard") == raw
            assert not readable.query(MessageDivider)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("owner context: lazy readable JSON/peer sections, original payload/copy, Markdown and user quotes preserved")


if __name__ == "__main__":
    asyncio.run(main())
