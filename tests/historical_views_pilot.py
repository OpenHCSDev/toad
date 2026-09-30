"""Normal Comms mounted history crosses source boundaries and opens saved sessions."""
from toad.navigation_target import NavigationContext

from toad.navigation_target import channel_target

import asyncio
import json
import os
import tempfile
from pathlib import Path

from agent_comms import HistoricalMessage
from agent_comms.threads import Thread
from agent_comms.comms import wire
from agent_comms.read_ledger import ReadLedger
from runtime_fixture import ToadApp

from toad.screens.historical_sessions import HistoricalSessions
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.transcript_history import TranscriptHistory


async def until(pilot, predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await pilot.pause(0.03)


async def main():
    (Path(__file__).parent.parent / ".test-artifacts").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="history-pilot-", dir=Path(__file__).parent.parent / ".test-artifacts"
    ) as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "live"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
        )
        old = wire(root / "old")
        session = root / "old-session.jsonl"
        session.write_text(
            "".join(
                json.dumps(
                    {
                        "type": "message",
                        "id": str(i),
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": f"Saved original answer {i}"}
                            ],
                        },
                    }
                )
                + "\n"
                for i in range(45)
            )
        )
        old.registry.declare(
            Thread(
                "peer",
                frozenset({"team"}),
                str(root),
                session_file=str(session),
                created_at=10.0,
            )
        )
        for i in range(85):
            old.messaging.send("peer", "#team", f"OLD row {i}\n" + "source content\n" * 3)
        live = wire(root / "live")
        live.registry.declare(Thread("peer", frozenset({"team"}), str(root), created_at=20.0))
        viewer = live.messaging.user_identity(str(root)).name
        for i in range(3):
            live.messaging.send("peer", "#team", f"LIVE row {i}")
        source = live.views.attach_history(old.root)
        bus_before = (live.root / "bus.jsonl").read_bytes()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            await channel_target("#team").open(NavigationContext(app, app.selected_mode, root, viewer))
            chat = app.screen.query_one(CommsChatView)
            await until(pilot, lambda: chat.message_history.initialized)
            assert any(m.body.startswith("LIVE") for m, _ in chat.message_history.rows)
            # Scroll as the user does, including source cursor boundary.
            for _ in range(12):
                if not chat.message_history.has_older:
                    break
                first = chat.message_history.rows[0][0].view_cursor
                chat.window.scroll_home(animate=False, immediate=True)
                await until(
                    pilot,
                    lambda first=first: (
                        not chat.message_history.has_older or chat.message_history.rows[0][0].view_cursor != first
                    ),
                )
                await pilot.pause()
            assert chat.message_history.rows[0][0].body.startswith("OLD row 0\n")
            assert len({m.view_key for m, _ in chat.message_history.rows}) == len(chat.message_history.rows)
            assert any(isinstance(m, HistoricalMessage) for m, _ in chat.message_history.rows)
            await until(
                pilot,
                lambda: bool(
                    ReadLedger(Path(source.root) / ReadLedger.filename).read().messages
                ),
            )
            seen = live.bus.reads.seen_sequences(viewer, live.registry.snapshot())
            assert seen <= {1, 2, 3}
            # Reaching older history has not allocated live sequences or queued turns.
            assert (live.root / "bus.jsonl").read_bytes() == bus_before
            assert live.bus.log.latest_sequence() == 3
            await app.screen.action_historical_sessions()
            await until(pilot, lambda: isinstance(app.screen, HistoricalSessions))
            await until(pilot, lambda: bool(app.screen.query(TranscriptHistory)))
            history = app.screen.query_one(TranscriptHistory)
            await until(pilot, lambda: hasattr(history, "window"))
            assert history.pages[-1].page.events[-1].text == "Saved original answer 44"
            while history.has_older:
                before = (history.pages[0].page.before.offset, history.pages[0].start)
                history.window.scroll_home(animate=False, immediate=True)
                try:
                    await until(
                        pilot,
                        lambda before=before: (
                            (
                                history.pages[0].page.before.offset,
                                history.pages[0].start,
                            )
                            < before
                            or not history.has_older
                        ),
                    )
                except TimeoutError:
                    print(
                        "HISTORY DEBUG",
                        history.region,
                        history.window.content_region,
                        history.window.scroll_y,
                        history.window.max_scroll_y,
                        (not history.state.accepts_source_work),
                        history.state.accepts_publication,
                        history.window.follows_tail,
                        history.fragment_count,
                        [
                            (p.page.before.offset, p.start, p.stop)
                            for p in history.pages
                        ],
                        flush=True,
                    )
                    raise
                await pilot.pause()
            assert history.pages[0].page.events[0].text == "Saved original answer 0"
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen.query_one(CommsChatView), CommsChatView)
            # Historical sender links select the source incarnation, not the live peer.
            chat = app.screen.query_one(CommsChatView)
            original_widget = next(
                widget
                for message, widget in chat.message_history.rows
                if isinstance(message, HistoricalMessage)
            )
            original_widget.action_open_sender()
            await until(pilot, lambda: isinstance(app.screen, HistoricalSessions))
            assert app.screen.threads[0].thread.created_at == 10.0
            await pilot.press("escape")
            await pilot.pause()
            assert live.registry.require("peer").created_at == 20.0
            assert app._exception is None
    print(
        "Mounted normal Comms: 85 historical + 3 live rows, colliding sequences, sparse historical ACK, and 45 saved-session answers paginated; no live bus writes"
    )


if __name__ == "__main__":
    asyncio.run(main())
