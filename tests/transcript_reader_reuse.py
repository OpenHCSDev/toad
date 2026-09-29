"""An attachment reuses core page-reader caches without retaining stale routes."""

from toad.navigation_target import FeedTarget

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms.comms import Comms, wire
from agent_comms.routing import MessageRoute, TurnRouting
from agent_comms.threads import Thread
from comms_boundary_fixture import attach_coordination
from runtime_fixture import ToadApp

from toad.acp.agent import Agent


def record(identifier, text):
    return (
        json.dumps(
            {
                "id": identifier,
                "type": "message",
                "message": {"role": "assistant", "content": text},
            }
        )
        + "\n"
    )


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-page-reader-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
        )
        source = root / "session.jsonl"
        source.write_text(record("one", "First"))
        comms = Comms(root / "wire")
        comms.threads.register(
            Thread("fixture", frozenset(), str(root), session_file=str(source))
        )
        agent = Agent(
            root,
            {
                "name": "Fixture",
                "identity": "fixture",
                "short_name": "fixture",
                "run_command": {"*": "true"},
                "protocol": "acp",
            },
            "fixture",
        )
        attach_coordination(agent, str(root / "wire"), "fixture")
        with patch("toad.acp.transcript_reader.wire", wraps=wire) as create:
            pages = await asyncio.gather(
                *(agent.get_transcript_page() for _ in range(4))
            )
            assert create.call_count == 1
            assert all((page.events[0].text == "First" for page in pages))
            assert pages[0].events[0].routing is None
            route = TurnRouting(reply=MessageRoute("fixture", ("#test",)))
            comms.transcripts.routes.record(str(source), ("one",), route)
            changed = await agent.get_transcript_page()
            assert changed.events[0].routing == route, (
                "Retained reader missed a routing revision"
            )
            with source.open("a") as output:
                output.write(record("two", "Second"))
            appended = await agent.get_transcript_page(after=pages[0].after)
            assert [event.text for event in appended.events] == ["Second"]
            assert create.call_count == 1
            other = Comms(root / "other-wire")
            second = root / "other.jsonl"
            second.write_text(record("other", "Other wire"))
            other.threads.register(
                Thread("fixture", frozenset(), str(root), session_file=str(second))
            )
            attach_coordination(
                agent, str(root / "other-wire"), agent.coordination.thread.name
            )
            moved = await agent.get_transcript_page()
            assert [event.text for event in moved.events] == ["Other wire"]
            assert create.call_count == 2
        os.environ["AGENT_COMMS_ROOT"] = str(root / "wire")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            attachments = [
                Agent(
                    root,
                    {
                        "name": "Fixture",
                        "identity": "fixture",
                        "short_name": "fixture",
                        "run_command": {"*": "true"},
                        "protocol": "acp",
                    },
                    "fixture",
                )
                for _ in range(3)
            ]
            for attachment in attachments:
                attachment.attach_surface(app.selected_session.conversation)
                attach_coordination(attachment, str(root / "wire"), "fixture")
            with patch("toad.acp.transcript_reader.wire", wraps=wire) as create:
                await asyncio.gather(
                    *(attachment.get_transcript_page() for attachment in attachments)
                )
                assert create.call_count == 0
            for attachment in attachments:
                async with attachment.controller.transcripts.bind(str(app.coordination_wire.root)) as reader:
                    assert reader is app.coordination_wire
            owner_mode = app.selected_mode
            with (
                patch(
                    "toad.widgets.comms_chat.wire",
                    side_effect=AssertionError("new chat reader"),
                ),
                patch(
                    "toad.widgets.comms_sidebar.wire",
                    side_effect=AssertionError("new sidebar reader"),
                ),
            ):
                await app.open_comms_session(owner_mode=owner_mode, project_path=root,
                                             me="fixture", target=FeedTarget())
            from toad.widgets.comms_chat import CommsChatView
            from toad.widgets.comms_sidebar import CommsSidebar

            assert app.screen.query_one(CommsChatView)._wire is app.coordination_wire
            assert app.screen.query_one(CommsSidebar)._wire is app.coordination_wire
        await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "page reader: reused across concurrent pages; routing changes, appended replies and wire changes remain current"
    )


if __name__ == "__main__":
    asyncio.run(main())
