"""A rejected ACP prompt keeps its reason and a usable local diagnostics link."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import quote

from textual.widgets import Markdown
from toad.acp.agent import Agent
from toad.agent import AgentFail
from toad.app import ToadApp
from toad.conversation_markdown import _path_parser
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import Conversation
from toad.widgets.note import Note


async def main() -> None:
    with TemporaryDirectory(prefix="toad-agent-failure-") as directory:
        root = Path(directory)
        log_file = root / "ACP session log.txt"
        with patch.dict(os.environ, {
            "TOAD_LOG": str(log_file),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_STATE_HOME": str(root / "state"),
            "AGENT_COMMS_ROOT": str(root / "wire"),
        }):
            app = ToadApp(project_dir=str(root))
            async with app.run_test(size=(100, 35)) as pilot:
                conversation = app.screen.conversation
                agent = Agent(
                    root, {"name": "agent-comms", "run_command": {"*": "true"}}, None
                )
                # The pilot presents an already-running ACP owner; no worker or
                # directory watcher is needed to exercise the failure view.
                conversation.set_reactive(Conversation.agent, agent)
                conversation.set_reactive(Conversation.agent_ready, True)
                log_file.write_text("Pi native input-ID capability preflight failed.\n")
                try:
                    await conversation.on_agent_fail(AgentFail(
                        "Failed to send prompt",
                        "Pi native input-ID capability preflight failed.",
                        help="prompt",
                    ))
                    await pilot.pause()
                    notes = list(conversation.query(Note))
                    assert any(
                        "Pi native input-ID capability preflight failed." in str(note.render())
                        for note in notes
                    )
                    links = [
                        response for response in conversation.query(AgentResponse)
                        if "Open ACP log" in response.source
                    ]
                    assert len(links) == 1
                    hrefs = [
                        child.attrs.get("href")
                        for token in _path_parser(root).parse(links[0].source)
                        for child in (token.children or [])
                        if child.type == "link_open"
                    ]
                    assert hrefs == [f"toad-file:{quote(str(log_file))}"]
                    opened = []

                    async def capture_preview(path):
                        opened.append(path)

                    with patch.object(app.screen, "open_file_preview", capture_preview):
                        await links[0].on_markdown_link_clicked(
                            Markdown.LinkClicked(links[0], hrefs[0])
                        )
                    assert opened == [log_file]
                    assert not links[0].has_class("-unrouted")
                    assert any(
                        note.has_class("-error") and not note.has_class("-unrouted")
                        for note in notes
                    )
                    assert not any("failed to start" in response.source.lower()
                                   for response in conversation.query(AgentResponse))
                finally:
                    conversation.set_reactive(Conversation.agent, None)
                    await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
