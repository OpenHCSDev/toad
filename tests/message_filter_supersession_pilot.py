"""A late older-page result cannot publish rows from a previous filter."""

from agent_comms.transcript_events import IncomingTranscript

from toad.widgets.message_filter import InboundCategory, ThinkingCategory

import asyncio
import os
from pathlib import Path
import tempfile

from agent_comms.messages import Message, MessageType
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import AssistantTranscript, ThinkingTranscript, IncomingTranscript
from agent_comms.routing import MessageRoute

from runtime_fixture import ToadApp
from toad.widgets.message_filter import MessageCategory
from toad.widgets.transcript_history import TranscriptHistory



async def main():
    with tempfile.TemporaryDirectory(prefix="toad-filter-supersession-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 37)) as pilot:
            await pilot.pause()
            view = app.selected_session.conversation
            file = "fixture"
            cursor = TranscriptCursor(file, 100)
            entered, release = asyncio.Event(), asyncio.Event()
            message = Message('peer', 'owner', 'OLD_INBOUND', MessageType.INFO)
            incoming = IncomingTranscript(message.body, route=MessageRoute(message.sender, (message.target,)), source=message.reference)
            thinking = ThinkingTranscript('OLDER_THINKING')
            calls = []

            async def older(**kwargs):
                calls.append(kwargs)
                entered.set()
                await release.wait()
                return TranscriptPage((incoming, thinking), TranscriptCursor(file, 0), cursor, False, True)

            tail = tuple(AssistantTranscript(f'unselected {i}\n' + 'long text ' * 20)
                         for i in range(24))
            pager = TranscriptHistory(TranscriptPage(tail, cursor, TranscriptCursor(file, 200), True, False),
                                      loader=older)
            try:
                await view.contents.mount(pager)
                view.visible_categories = frozenset((InboundCategory,))
                view.window.release_anchor()
                view.window.scroll_to(y=0, animate=False, immediate=True)
                await asyncio.wait_for(entered.wait(), 5)
                view.visible_categories = frozenset((ThinkingCategory,))
                release.set()
                async with asyncio.timeout(8):
                    while (pager.filter.overlay is None or
                           not any(child.fragment.events[0].text == "OLDER_THINKING"
                                    for child in pager.filter.overlay.fragment_views)):
                        await pilot.pause(.02)
                assert all(child.fragment.events[0].text != "OLD_INBOUND"
                            for child in pager.filter.overlay.fragment_views)
                assert len(calls) <= 2 and view.window.follows_tail is False
                assert app._exception is None
            finally:
                release.set()
        await asyncio.get_running_loop().shutdown_default_executor()
    print("filter supersession: stale inbound page rejected; selected thinking page fills older history")


if __name__ == "__main__":
    asyncio.run(main())
