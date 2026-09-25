"""A long logical message keeps one divider through saved and live pagination."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import (
    Message, MessageRoute, MessageType, TranscriptCursor, TranscriptEvent, TranscriptPage,
    TurnRouting,
)
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.incoming_message import IncomingSender
from toad.widgets.message_divider import MessageDivider
from toad.widgets.route_header import RouteHeader
from toad.widgets.transcript_fragments import transcript_fragments
from toad.widgets.transcript_history import TranscriptHistory, TranscriptPageView


async def main() -> None:
    text = "## Context compacted\n\n" + "\n\n".join(
        f"### Section {index}\n" + "A retained fact. " * 38 for index in range(8)
    )
    cursor = TranscriptCursor("", 0)
    page = TranscriptPage((TranscriptEvent("notice", text),), cursor, cursor, False, False)
    fragments = transcript_fragments(page.events)
    assert len(fragments) >= 4
    with tempfile.TemporaryDirectory(prefix="toad-fragment-divider-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            conversation = app.screen.conversation
            await conversation.contents.remove_children()
            saved = TranscriptPageView(page, newest=False, fragments=fragments)
            await conversation.post(saved)
            await pilot.pause()
            assert len(saved.query(MessageDivider)) == 1, "saved notice got repeated timestamps"

            await conversation.contents.remove_children()
            route = MessageRoute("worker", ("#updates",))
            sent_page = TranscriptPage(
                (TranscriptEvent("sent", text, routing=TurnRouting(reply=route)),),
                cursor, cursor, False, False,
            )
            sent = TranscriptPageView(
                sent_page, newest=False, fragments=transcript_fragments(sent_page.events),
            )
            await conversation.post(sent)
            await pilot.pause()
            assert len(sent.query(MessageDivider)) == 1
            assert len(sent.query(RouteHeader)) == 1, "saved route header repeated in fragments"

            await conversation.contents.remove_children()
            incoming = Message("worker", "#updates", text, MessageType.INFO)
            user_page = TranscriptPage(
                (TranscriptEvent("user", text, routing=TurnRouting(requests=(incoming,))),),
                cursor, cursor, False, False,
            )
            user = TranscriptPageView(
                user_page, newest=False, fragments=transcript_fragments(user_page.events),
            )
            await conversation.post(user)
            await pilot.pause()
            assert len(user.query(MessageDivider)) == 1
            assert len(user.query(IncomingSender)) == 1, "inbound header repeated in fragments"

            await conversation.contents.remove_children()
            live = await conversation.post(AgentResponse(text))
            async with asyncio.timeout(10):
                while not live.query(TranscriptHistory):
                    await pilot.pause(.05)
            assert len(live.query(MessageDivider)) == 1, "live message got nested timestamps"
    print("fragment dividers: one per logical saved or live message")


if __name__ == "__main__":
    asyncio.run(main())
