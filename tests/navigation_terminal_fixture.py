"""Deterministic read-only terminal fixture; no provider or live owner processes.

The ordinary UI and core wire model are used with fixed saved-history responses.
This isolates renderer/navigation cost from changing production owner schemas.
"""

import asyncio
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from agent_comms.messages import Message, MessageType
from agent_comms.routing import MessageRoute, TurnRouting
from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import AssistantTranscript, NoticeTranscript, SentTranscript, ThinkingTranscript, ToolEndTranscript, ToolStartTranscript, UserTranscript
from agent_comms.comms import wire
from setproctitle import setproctitle

from toad.acp.agent import Agent
from toad.acp.messages import CoordinationUpdate, TranscriptSnapshot
from toad.agent import AgentReady
from toad.app import ToadApp
from toad.render_backend import RendererBackend, create_renderer
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.message_filter import event_category


async def main():
    from sidebar_validation_driver import install_observer

    install_observer()
    setproctitle("toad")
    with tempfile.TemporaryDirectory(prefix="toad-fixed-terminal-", dir=os.environ.get("TOAD_ARTIFACT_ROOT")) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        names = ("fixture-owner", *(f"fixture-{index:02}" for index in range(24)))
        for name in names:
            comms.threads.register(Thread(name, frozenset({"fixture"}), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
        for index in range(100):
            comms.messaging.send("fixture-00", "#fixture", f"Wire record {index}: " + "fixed content " * 12)
        events = tuple(
            kind(f"## {kind.declared_name} record {index}\n\n" + text)
            for index in range(180)
            for kind, text in (
                (UserTranscript, "A user paragraph with **formatting**. " * 8),
                (AssistantTranscript, "A saved answer with text.\n\n" * 6),
                (ThinkingTranscript, "A reasoning paragraph. " * 6),
            )
        )
        identity = hashlib.sha256(json.dumps([(event.declared_name, event.text) for event in events]).encode()).hexdigest()
        all_categories = os.environ.get("TOAD_FIXTURE_ALL_CATEGORIES") == "1"
        if all_categories:
            mixed = []
            for index in range(90):
                body = f"INBOUND_{index}: typed routed content. " * 3
                incoming = Message("fixture-00", "fixture-owner", body, MessageType.INFO, timestamp=0)
                tool_id = f"fixture-read-{index}"
                mixed.extend((
                    UserTranscript(f'USER_{index}: ordinary user text. ' * 4),
                    AssistantTranscript(f'AGENT_{index}: ordinary assistant text. ' * 4),
                    UserTranscript(body, routing=TurnRouting((incoming,), None)),
                    SentTranscript(f'OUTBOUND_{index}: routed answer. ' * 4, routing=TurnRouting((), MessageRoute('fixture-owner', ('fixture-00',)))),
                    ThinkingTranscript(f'THINKING_{index}: reasoning text. ' * 4),
                    ToolStartTranscript(tool_call_id=tool_id, tool_name='Read', raw_input={'path': 'fixture.py'}),
                    ToolEndTranscript(tool_call_id=tool_id, tool_name='Read', text=f'TOOL_{index}: saved tool result'),
                    NoticeTranscript(f'OTHER_{index}: saved notice. ' * 4),
                ))
            events = tuple(mixed)
            identity = hashlib.sha256(json.dumps([asdict(event) for event in events], sort_keys=True, default=str).encode()).hexdigest()

        async def page(self, *, before=None, after=None, through=None):
            ceiling = through.offset if through is not None else len(events)
            if after is not None:
                start, stop = after.offset, min(ceiling, after.offset + 20)
            else:
                stop = min(ceiling, before.offset if before is not None else ceiling)
                start = max(0, stop - 20)
            return TranscriptPage(events[start:stop], TranscriptCursor(identity, start),
                                  TranscriptCursor(identity, stop), start > 0, stop < ceiling)

        async def start(agent, target):
            agent._message_target = target

            async def deliver():
                initial = await page(agent)
                target.post_message(TranscriptSnapshot(initial.events, initial))
                target.post_message(AgentReady())

            agent._task = asyncio.create_task(deliver())

        data = {"name": "Read-only fixture", "identity": "fixture", "short_name": "fixture",
                "run_command": {"*": "/bin/false"}, "protocol": "acp"}
        app = ToadApp(project_dir=str(root), renderer=create_renderer(RendererBackend.PERSISTENT))
        with patch.object(Agent, "start", start), patch.object(Agent, "get_transcript_page", page):
            async with app.run_test(headless=False, size=None, tooltips=True, notifications=True) as pilot:
                await pilot.pause()
                screen = app.screen
                screen._agent = data
                await screen.on_coordination_update(CoordinationUpdate(
                    thread="fixture-owner", wire_root=str(comms.root), persistence="fixture", transport="fixture"))
                agent = Agent(root, data, "fixture-owner")
                agent._message_target = screen.conversation
                screen.conversation.set_reactive(type(screen.conversation).agent, agent)
                screen.conversation.agent_ready = True
                await screen.conversation.contents.mount(TranscriptHistory(await page(agent), agent.get_transcript_page))
                await pilot.pause()
                Path(os.environ["TOAD_FIXTURE_READY"]).write_text(json.dumps({
                    "pid": os.getpid(), "driver": os.environ["TEXTUAL_DRIVER"],
                    "source_sha256": identity, "native_events": len(events),
                    "wire_messages": 100, "root": str(root),
                    "fixture_kind": "all-categories" if all_categories else "navigation",
                    "category_counts": dict(Counter(event_category(event).value for event in events)),
                }))
                await app._task
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
