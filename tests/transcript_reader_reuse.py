"""An attachment reuses core page-reader caches without retaining stale routes."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from agent_comms import Comms, MessageRoute, Thread, TurnRouting, wire
from toad.acp.agent import Agent
from runtime_fixture import ToadApp


def record(identifier, text):
    return json.dumps({"id": identifier, "type": "message",
                       "message": {"role": "assistant", "content": text}}) + "\n"


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-page-reader-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        source = root / "session.jsonl"
        source.write_text(record("one", "First"))
        comms = Comms(root / "wire")
        comms.register(Thread("fixture", frozenset(), str(root), session_file=str(source)))
        agent = Agent(root, {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
                             "run_command": {"*": "true"}, "protocol": "acp"}, "fixture")
        agent._coordination_root, agent._coordination_thread = str(root / "wire"), "fixture"
        with patch("agent_comms.wire", wraps=wire) as create:
            pages = await asyncio.gather(*(agent.get_transcript_page() for _ in range(4)))
            assert create.call_count == 1
            assert all(page.events[0].text == "First" for page in pages)
            assert pages[0].events[0].routing is None
            route = TurnRouting(reply=MessageRoute("fixture", ("#test",)))
            comms.transcript_routes.record(str(source), ("one",), route)
            changed = await agent.get_transcript_page()
            assert changed.events[0].routing == route, "Retained reader missed a routing revision"
            with source.open("a") as output:
                output.write(record("two", "Second"))
            appended = await agent.get_transcript_page(after=pages[0].after)
            assert [event.text for event in appended.events] == ["Second"]
            assert create.call_count == 1
            # Moving the attachment to another wire must retire the old reader.
            other = Comms(root / "other-wire")
            second = root / "other.jsonl"
            second.write_text(record("other", "Other wire"))
            other.register(Thread("fixture", frozenset(), str(root), session_file=str(second)))
            agent._coordination_root = str(root / "other-wire")
            moved = await agent.get_transcript_page()
            assert [event.text for event in moved.events] == ["Other wire"]
            assert create.call_count == 2
        os.environ["AGENT_COMMS_ROOT"] = str(root / "wire")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            attachments = [Agent(root, {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
                                       "run_command": {"*": "true"}, "protocol": "acp"}, "fixture")
                           for _ in range(3)]
            for attachment in attachments:
                attachment._message_target = app.screen.conversation
                attachment._coordination_root = str(root / "wire")
                attachment._coordination_thread = "fixture"
            with patch("agent_comms.wire", wraps=wire) as create:
                await asyncio.gather(*(attachment.get_transcript_page() for attachment in attachments))
                assert create.call_count == 0
            assert all(attachment._transcript_reader is app.coordination_wire for attachment in attachments)
            owner_mode = app.current_mode
            with patch("agent_comms.operations.wire", side_effect=AssertionError("new reader on channel open")):
                await app.open_comms_session(owner_mode=owner_mode, project_path=root,
                                             me="fixture", target="#all", kind="irc")
            from toad.widgets.comms_chat import CommsChatView
            from toad.widgets.comms_sidebar import CommsSidebar

            assert app.screen.query_one(CommsChatView)._wire is app.coordination_wire
            assert app.screen.query_one(CommsSidebar)._wire is app.coordination_wire
        await asyncio.get_running_loop().shutdown_default_executor()
    print("page reader: reused across concurrent pages; routing changes, appended replies and wire changes remain current")


if __name__ == "__main__":
    asyncio.run(main())
