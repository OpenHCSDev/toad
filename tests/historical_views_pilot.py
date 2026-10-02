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


async def installed_handling(root: Path):
    """Actual native saved source and LinuxDriver; no provider or public owner."""
    import hashlib
    import subprocess
    import sys
    import time
    from toad.app import ToadApp as InstalledApplication
    from toad.widgets.wire_message_handling import WireMessageHandling
    from toad.widgets.incoming_message import IncomingMessage
    from toad.widgets.outgoing_message import OutgoingMessage
    from toad.widgets.message_notifications import MessageNotifications
    from textual.widgets import Select
    from agent_comms.field_codec import FieldCodec
    from agent_comms.bus_publication import stable_thread_lookup

    root.mkdir(parents=True, exist_ok=False)
    os.environ.update(AGENT_COMMS_ROOT=str(root / "live"),
                      XDG_CONFIG_HOME=str(root / "config"),
                      XDG_STATE_HOME=str(root / "state"),
                      XDG_DATA_HOME=str(root / "data"))
    assert os.environ.get("DISPLAY") and os.environ["DISPLAY"] != ":0"
    activation = json.loads((Path(sys.prefix) / "activation.json").read_text())
    started = time.monotonic()
    receipt = {"state": "running", "prefix": sys.prefix,
               "pins": activation["pins"], "checks": [],
               "provider_calls": 0, "public_mutations": 0}
    old = wire(root / "old")
    script = """
import {pathToFileURL} from 'node:url';
import {join} from 'node:path';
const {SessionManager}=await import(pathToFileURL(join(process.argv[1],'dist/core/session-manager.js')));
const manager=SessionManager.create(process.argv[2],join(process.argv[2],'sessions'));
manager.appendMessage({role:'user',content:'Original saved user request',timestamp:1});
console.log(manager.getSessionFile());
"""
    for index, name in enumerate(("alpha", "beta")):
        project = root / name
        project.mkdir()
        session = subprocess.check_output(
            ["node", "--input-type=module", "-e", script,
             activation["native_package"], str(project)], text=True, timeout=10).strip()
        old.registry.declare(Thread(name, frozenset({"team"}), str(project),
                                    session_file=session, created_at=10.0 + index))
    original_out = old.messaging.send_message("alpha", "beta", "ORIGINAL outgoing alpha to beta")
    original_in = old.messaging.send_message("beta", "alpha", "ORIGINAL incoming beta to alpha")
    live = wire(root / "live")
    for index, name in enumerate(("alpha", "beta")):
        live.registry.declare(Thread(name, frozenset({"team"}), str(root / "live-project"),
                                     created_at=20.0 + index))
    live.messaging.send_message("alpha", "beta", "WRONG live outgoing")
    live.messaging.send_message("beta", "alpha", "WRONG live incoming")
    live.views.attach_history(old.root)
    threads = live.views.historical_threads()
    frozen = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
              for source in (root / "old", root / "live")
              for p in source.rglob("*") if p.is_file()}
    (root / "protected-before.json").write_text(json.dumps(frozen, indent=2) + "\n")
    app = InstalledApplication(project_dir=str(root / "live-project"), mode="store")

    async def physical(pilot, widget):
        window = subprocess.check_output(["xdotool", "search", "--class", "st"],
                                         text=True).splitlines()[-1]
        geometry = subprocess.check_output(["xdotool", "getwindowgeometry", "--shell", window],
                                           text=True)
        dims = dict(line.split("=", 1) for line in geometry.splitlines() if "=" in line)
        x, y = widget.region.x + 2, widget.region.y
        px = 2 + int((x + .5) * (int(dims["WIDTH"]) - 4) / app.size.width)
        py = 2 + int((y + .5) * (int(dims["HEIGHT"]) - 4) / app.size.height)
        subprocess.run(["xdotool", "mousemove", "--window", window, str(px), str(py),
                        "click", "1"], check=True)
        await pilot.pause(.1)

    def screenshot(name):
        subprocess.run(["import", "-window", "root", str(root / (name + ".png"))],
                       check=True, timeout=5)
        (root / (name + ".svg")).write_text(app.export_screenshot())

    async def inspected(pilot, selected):
        screen = app.screen
        await until(pilot, lambda: bool(WireMessageHandling.within(screen)))
        bodies = WireMessageHandling.within(screen)
        assert {type(body) for body in bodies} == {IncomingMessage, OutgoingMessage}
        refs = WireMessageHandling.references_in(bodies)
        assert set(refs) == {original_out.reference, original_in.reference}
        item = threads[selected]
        original_service = __import__("agent_comms.comms", fromlist=["Comms"]).Comms(
            Path(item.source.root), private_initial_writes=False, private_claim_writes=False)
        from agent_comms import HistoricalMessage
        messages = tuple(HistoricalMessage.project(message, item.source,
                           live.bus.history.sources().index(item.source), item.source.provenance)
                         for message in original_service.bus.log.messages_for_references(refs))
        expected = original_service.views.message_notifications(messages)
        assert all(not message.notification_references() for message in messages)
        await until(pilot, lambda: all(body.query_one(MessageNotifications)._notifications is not None
                                     for body in bodies))
        rows = []
        for body in bodies:
            feedback = body.query_one(MessageNotifications)
            reference = body.message_reference
            assert feedback._notifications == expected[reference.seq, reference.message_id]
            assert all(n.recipient_identity.recipient_lookup not in {
                stable_thread_lookup(live.registry.require("alpha").created_at),
                stable_thread_lookup(live.registry.require("beta").created_at),
            } for n in feedback._notifications)
            rows.append({"widget": type(body).__name__, "reference": FieldCodec.encode(reference),
                         "title": str(feedback.title), "details": str(feedback.details.render())})
        receipt["checks"].append({"selected": item.thread.name,
                                  "original_created_at": item.thread.created_at,
                                  "source": item.source.key, "rows": rows})
        await physical(pilot, bodies[-1].query_one(MessageNotifications).query_one("CollapsibleTitle"))
        await pilot.pause(.2)
        screenshot("historical-" + item.thread.name)

    try:
        async with app.run_test(headless=False, size=None) as pilot:
            await app.push_screen(HistoricalSessions(live, threads))
            await inspected(pilot, 0)
            selector = app.screen.query_one("#saved-identity", Select)
            await physical(pilot, selector)
            subprocess.run(["xdotool", "key", "Down", "Return"], check=True)
            await until(pilot, lambda: selector.value == 1)
            await inspected(pilot, 1)
            await physical(pilot, selector)
            subprocess.run(["xdotool", "key", "Up", "Return"], check=True)
            await until(pilot, lambda: selector.value == 0)
            await inspected(pilot, 0)
            subprocess.run(["xdotool", "key", "Escape"], check=True)
            await until(pilot, lambda: not isinstance(app.screen, HistoricalSessions))
            assert app._exception is None
        changed = [path for path, digest in frozen.items()
                   if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest]
        assert not changed, changed
        receipt.update(state="passed", protected_files=len(frozen),
                       original_and_live_bytes_unchanged=True,
                       native_source="actual SessionManager journals + canonical archived wire")
    except BaseException as error:
        receipt.update(state="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        receipt["elapsed_seconds"] = time.monotonic() - started
        (root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    import sys
    try:
        asyncio.run(installed_handling(Path(sys.argv[2])) if sys.argv[1:2] == ["--installed-handling"] else main())
    except BaseException:
        import traceback
        if sys.argv[1:2] == ["--installed-handling"]:
            Path(sys.argv[2]).with_suffix(".terminal-error.txt").write_text(traceback.format_exc())
        raise
