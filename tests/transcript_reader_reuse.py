"""An attachment reuses core page-reader caches without retaining stale routes."""
import asyncio
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_comms.comms import Comms, wire
from agent_comms.acp_extension import TranscriptSnapshotUpdate
from agent_comms.field_codec import FieldCodec
from agent_comms.transcripts import TranscriptRead
from toad.acp.transcript_reader import NativeTranscriptReadWork
from agent_comms.routing import MessageRoute, TurnRouting
from agent_comms.threads import Thread
from comms_boundary_fixture import attach_coordination
from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition


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
        comms.registry.declare(
            Thread("fixture", frozenset(), str(root), session_file=str(source))
        )
        agent = Agent(
            root,
            AgentDefinition.decode({
                "name": "Fixture",
                "identity": "fixture",
                "short_name": "fixture",
                "run_command": {"*": "true"},
                "protocol": "acp",
            }),
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
            other.registry.declare(
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
                    AgentDefinition.decode({
                        "name": "Fixture",
                        "identity": "fixture",
                        "short_name": "fixture",
                        "run_command": {"*": "true"},
                        "protocol": "acp",
                    }),
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
                async with attachment.controller.transcripts.bind(str(app.coordination_access.service.root)) as reader:
                    assert reader is app.coordination_access.service
            # Actual ACP publication and canonical page requests share one key.
            reader = app.coordination_access.service
            source.write_text(source.read_text() + record("publication", "Published without a UI read"))
            read = reader.transcripts.capture_page_read("fixture")
            snapshot = TranscriptSnapshotUpdate(read.read(), read.identity)
            decoded = FieldCodec.decode(TranscriptSnapshotUpdate, FieldCodec.encode(snapshot))
            assert NativeTranscriptReadWork(read).work_key == NativeTranscriptReadWork(
                TranscriptRead(reader.transcripts, decoded.identity)).work_key
            before = reader.transcripts.page_reads
            await attachments[0].controller.transcripts.publication(decoded)
            assert await attachments[0].get_transcript_page() == snapshot.page
            assert reader.transcripts.page_reads == before, "Published page was read again"
            # An actual registry annotation changes the observation without
            # changing this original content. Its published page stays admitted.
            reader.registry.register(replace(reader.registry.require("fixture"), title="Annotation changed"))
            assert not read.current() and read.content_current()
            annotation_read = reader.transcripts.capture_page_read("fixture")
            assert NativeTranscriptReadWork(read).work_key == NativeTranscriptReadWork(annotation_read).work_key
            annotated = await attachments[0].controller.transcripts.publication(decoded)
            assert annotated.page == snapshot.page
            assert await attachments[0].get_transcript_page() == snapshot.page
            assert reader.transcripts.page_reads == before, "Annotations reread original content"
            source.write_text(source.read_text() + record("three", "Changed after publication"))
            current = await attachments[0].controller.transcripts.publication(decoded)
            assert current.identity != decoded.identity
            assert current.page.events[-1].text == "Changed after publication"
            assert reader.transcripts.page_reads == before + 1, "Stale publication must recapture"
        await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "page reader: reused across concurrent pages; routing changes, appended replies and wire changes remain current"
    )


if __name__ == "__main__":
    asyncio.run(main())
