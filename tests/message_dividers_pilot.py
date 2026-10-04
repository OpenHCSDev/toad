
from agent_comms.transcript_events import IncomingTranscript
from toad.navigation_target import NavigationContext
from toad.live_output import ResponseStream
"""Full-width timed headers stay inside text blocks across native and wire views."""

from toad.navigation_target import channel_target

import asyncio
import os
import tempfile
import time
from pathlib import Path

from agent_comms.routing import MessageRoute
from agent_comms.threads import Thread
from agent_comms.comms import wire
from runtime_fixture import ToadApp

from toad.response_delivery import ResponseDelivery
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.comms_chat import CommsChatView, session_thread_name
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.irc_message import IRCMessage, WireMarkdownMessage
from toad.widgets.message_divider import MessageDivider
from toad.widgets.tool_call import ToolCall
from toad.widgets.user_input import UserInput


async def row_publication() -> None:
    """Exercise the actual source writer and pump during native row retirement."""
    import json
    from time import monotonic
    from textual import events
    from textual.geometry import Size
    from textual.worker import WorkerState
    from retained_tool_text_pilot import PublicationApp, PendingUnmount
    from runtime_fixture import private_native_wire, refresh_comms
    from toad.screens.comms import CommsScreen
    from toad.transcript_state import ParkedSourceTranscript
    from toad.mounted_message_history import IrcMessageStyle, HISTORY_PAGE_SIZE

    started = monotonic()
    checks = []
    with tempfile.TemporaryDirectory(prefix="toad-row-publication-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        comms = private_native_wire(root / "wire")
        me = session_thread_name(root)
        comms.registry.declare(Thread(me, frozenset(), str(root)))
        comms.registry.declare(Thread("peer", frozenset(), str(root)))
        for index in range(24):
            comms.messaging.send_message("peer", "#all", f"original row {index}")
        app = PublicationApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            await pilot.pause()
            owner = app.selected_mode
            await channel_target("#all").open(NavigationContext(app, owner, root, me))
            await app.selected_session.wait_content_ready()
            chat = app.screen.query_one(CommsChatView)
            history = chat.message_history
            await refresh_comms(chat)
            await pilot.pause()
            assert history.rows and all(isinstance(widget, IRCMessage) for _, widget in history.rows)
            keys = tuple(message.view_key for message, _ in history.rows)
            screen = chat.query_ancestor(CommsScreen)
            old_rows = tuple(history.rows)
            page = await history.reader.page(limit=HISTORY_PAGE_SIZE)
            await history.mount_page(page, older=True)
            old_rows = tuple(history.rows)
            keys = tuple(message.view_key for message, _ in old_rows)
            history.window.scroll_end(animate=False)
            assert page.display_scope is not None
            receipt_sequence = old_rows[0][0].seq
            assert history.channel_receipts[receipt_sequence] is page
            held = PendingUnmount()
            await old_rows[-1][1].mount(held)
            await pilot.pause()
            admitted = asyncio.Event()
            admitted_workers = []

            def start_style():
                screen.action_message_style()
                admitted_workers.append(next(worker for worker in history.workers
                    if worker.node is history and worker.group == "message-style"
                    and worker not in admitted_workers))
                admitted.set()

            try:
                screen.call_later(start_style)
                async with asyncio.timeout(8):
                    await admitted.wait()
                    await held.entered.wait()
                first = admitted_workers[0]
                async with asyncio.timeout(8):
                    await first.wait()
                assert first.is_finished and not held.release.is_set()
                assert tuple(message.view_key for message, _ in history.rows) == keys
                assert all(type(widget) is WireMarkdownMessage for _, widget in history.rows)
                assert not history.window.history_mutating() and app._batch_count == 0
                assert held not in app.screen._compositor.full_map
                assert history.channel_receipts[receipt_sequence] is page
                checks.append("source completes and authenticated receipt survives style commit before old Unmount")
                reader = history.reader
                reader.restart()
                read = await reader.read(history.follows_tail)
                assert read.replace_tail and read.page is not None
                async with asyncio.timeout(8):
                    assert await history.publish(read)
                assert reader.source is not read.request and not reader.source.loading
                assert reader.source.display_identity == read.request.kind.display_identity(read.page)
                assert (history.has_older, history.has_newer) == (read.page.has_older, read.page.has_newer)
                assert not held.release.is_set()
                keys = tuple(message.view_key for message, _ in history.rows)
                checks.append("actual replacement read commits authenticated source and both bounds before old Unmount")
                history.window.scroll_end(animate=False)
                app.displayed.clear()
                size = Size(108, 36)
                app._driver._size = size
                app.post_message(events.Resize(size, size))
                async with asyncio.timeout(8):
                    await app.displayed.wait()
                visible = app.screen._compositor.visible_widgets
                bodies = tuple(widget.query_one(AgentResponse) for _, widget in history.rows)
                displayed = tuple(body for body in bodies if body in visible)
                assert displayed and all(body.body_ready for body in displayed)
                app.observed_body = displayed[-1]
                assert first.is_finished and not held.release.is_set()
                checks.append("actual resize/current-source native display admission before old Unmount ends")
                editor = chat.prompt.prompt_text_area
                app.screen.set_focus(editor, scroll_visible=False)
                await app._press_keys("style-pump")
                pumped = asyncio.Event()
                screen.call_later(pumped.set)
                async with asyncio.timeout(5):
                    await pumped.wait()
                assert "style-pump" in editor.text and first.is_finished
                checks.append("editor input and same CommsScreen pump remain admitted during style worker")
                admitted.clear()
                screen.call_later(start_style)
                async with asyncio.timeout(5):
                    await admitted.wait()
                second = admitted_workers[-1]
                async with asyncio.timeout(5):
                    await second.wait()
                assert second.is_finished and not held.release.is_set()
            finally:
                app.observed_body = None
                held.release.set()
            await first.wait()
            await second.wait()
            await pilot.pause()
            assert tuple(message.view_key for message, _ in history.rows) == keys
            assert all(isinstance(widget, IRCMessage) for _, widget in history.rows)
            assert "style-pump" in editor.text
            checks.append("each repeated style request commits in original source order without losing draft")
            page = await history.reader.page(limit=8)
            before = tuple(history.rows)
            geometry = history.window._geometry_revision
            await history.mount_page(page, older=False)
            assert tuple(history.rows) == before
            assert history.window._geometry_revision == geometry
            checks.append("unchanged native rows do not manufacture reader layout")
            held = PendingUnmount()
            await history.rows[-1][1].mount(held)
            await pilot.pause()
            admitted.clear()
            screen.call_later(start_style)
            try:
                async with asyncio.timeout(8):
                    await admitted.wait()
                    await held.entered.wait()
                committed = tuple(history.rows)
                assert tuple(message.view_key for message, _ in committed) == keys
                assert all(type(widget) is WireMarkdownMessage for _, widget in committed)
                async with asyncio.timeout(5):
                    await history.retire_source(parked=True)
                assert isinstance(history.state, ParkedSourceTranscript)
                assert tuple(history.rows) == committed and not held.release.is_set()
                assert not history.window.history_mutating() and app._batch_count == 0
                assert all(worker.is_finished for worker in history.workers
                           if worker.node is history), [
                               (worker.group, worker.state) for worker in history.workers
                               if worker.node is history]
                checks.append("source park joins cancelled row worker while native retirement keeps committed rows")
            finally:
                held.release.set()
            await held._task
            history.resume_source()
            await refresh_comms(chat)
            await pilot.pause()
            assert history.rows and "style-pump" in editor.text
            checks.append("original source park/resume retains admitted native rows and draft")

            entered = asyncio.Event()
            release = asyncio.Event()

            class AcquiringRow(IRCMessage):
                async def on_mount(self):
                    entered.set()
                    await release.wait()

            class AcquiringStyle(IrcMessageStyle):
                row_type = AcquiringRow

            replacement = await history.reader.page(limit=HISTORY_PAGE_SIZE)
            for acknowledgement in tuple(history.workers):
                if acknowledgement.node is chat and acknowledgement.group == "comms-painted-read":
                    await acknowledgement.wait()
            committed = tuple(history.rows)
            receipts = dict(history.channel_receipts)
            historical = dict(history.historical_receipts)
            tail = history.tail_receipt
            bounds = history.has_older, history.has_newer
            style = history.style

            async def acquire():
                async with history.window.history_lock:
                    await history._mount_page(replacement, older=False,
                                              retained=(), style=AcquiringStyle())

            worker = history.run_worker(acquire, group="message-style")
            try:
                async with asyncio.timeout(8):
                    await entered.wait()
                assert tuple(history.rows) == committed
                assert history.channel_receipts == receipts and history.historical_receipts == historical
                assert history.tail_receipt is tail and (history.has_older, history.has_newer) == bounds
                assert history.style is style
                parking = asyncio.create_task(history.retire_source(parked=True))
                # Source retirement publishes its disposition before joining
                # the real acquiring worker; the native Mount must still exit.
                await asyncio.sleep(0)
                assert isinstance(history.state, ParkedSourceTranscript)
            finally:
                release.set()
            async with asyncio.timeout(8):
                await parking
            assert worker.state is WorkerState.CANCELLED and tuple(history.rows) == committed
            assert history.channel_receipts == receipts and history.historical_receipts == historical
            assert history.tail_receipt is tail and (history.has_older, history.has_newer) == bounds
            assert history.style is style and not history.query(AcquiringRow)
            assert not history.window.history_mutating() and app._batch_count == 0
            history.resume_source()
            checks.append("interrupted real native Mount preserves committed rows, style, bounds and receipt resources")

            archive = private_native_wire(root / "archive")
            archive.registry.declare(Thread("peer", frozenset(), str(root)))
            for index in range(2):
                archive.messaging.send_message("peer", "#all", f"archived row {index}")
            comms.views.attach_history(archive.root)
            history.reader.restart()
            read = await history.reader.read(history.follows_tail)
            assert await history.publish(read)
            async with asyncio.timeout(8):
                while history.has_older:
                    await history._load_page(True)
            original = tuple(message.view_key for message, _ in history.rows)
            assert any(source for source, _ in original)
            assert len({message.seq for message, _ in history.rows}) < len(original)
            await history.toggle_style()
            assert tuple(message.view_key for message, _ in history.rows) == original
            assert "style-pump" in editor.text
            checks.append("real attached history and live rows sharing sequence numbers restyle without synthetic backend page")
            assert app._exception is None
        assert app._exception is None
        checks.append("whole original App/runtime cleanup")
    if output := os.environ.get("TOAD_ROW_PUBLICATION_RECEIPT"):
        Path(output).write_text(json.dumps({"state": "affected installed App complete", "seconds": monotonic()-started,
                                          "checks": checks, "native_display_boundary": True,
                                          "physical_or_cpu_claim": False}, indent=2)+"\n")
    print("\n".join(checks))


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-message-dividers-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        comms.registry.declare(Thread("peer", frozenset(), str(root)))
        me = session_thread_name(root)
        comms.registry.declare(Thread(me, frozenset(), str(root)))
        sent = comms.messaging.send_message("peer", "#all", "incoming wire")
        outbound = comms.messaging.send_message(me, "#all", "outbound wire")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            owner = app.selected_mode
            native = app.selected_session.conversation
            user = await native.post(UserInput("human text"))
            reply = await native.output.append(ResponseStream(), "agent text")
            assert reply is not None
            incoming = await native.post(IncomingMessage(IncomingTranscript(sent.body, route=MessageRoute(sent.sender, (sent.target,)), source=sent.reference, timestamp=sent.timestamp)))
            thought = await native.post(AgentThought("not a displayed message"))
            tool = await native.post(ToolCall({"toolCallId": "tool-one", "title": "Read source"}))
            await pilot.pause()
            assert len(user.query(MessageDivider)) == 1
            assert "User" in user.query_one(MessageDivider).render().plain
            assert len(reply.query(MessageDivider)) == 1
            assert len(incoming.query(MessageDivider)) == 1
            assert not thought.query(MessageDivider)
            assert not tool.query(MessageDivider)
            routed = await native.post(AgentResponse(
                "routed answer", delivery=ResponseDelivery.from_route(MessageRoute(me, ("#all",))),
            ))
            await pilot.pause()
            assert "Outbound" in routed.query_one(MessageDivider).render().plain
            for block in (user, reply, incoming):
                divider = block.query_one(MessageDivider)
                assert divider.render().plain.startswith("─")
                assert divider.render().plain.endswith("─")
                assert divider.render().plain.count("─") > 4
                assert divider.render().cell_length == divider.size.width
                assert ":" in divider.render().plain

            for theme in ("ansi-dark", "textual-dark"):
                app.theme = theme
                user.scroll_visible(animate=False, immediate=True, top=True)
                await pilot.pause()
                divider = user.query_one(MessageDivider)
                rows = app.screen._compositor.render_strips()
                assert divider.region.x == user.region.x, "User divider is inset by an outer border"
                assert rows[divider.region.y].text[user.region.x] == "─"
                assert all(rows[y].text[user.region.x].isspace()
                           for y in range(user.region.y, divider.region.y)), (
                    "User accent must not extend above the divider", theme,
                )
                assert user.get_clipboard_text() == "human text"

            await channel_target("#all").open(NavigationContext(app, owner, root, app.session_navigation.source(owner)._comms_thread))
            chat = app.screen.query_one(CommsChatView)
            async with asyncio.timeout(5):
                while not any(message.seq == sent.seq for message, _ in chat.message_history.rows):
                    await pilot.pause(.05)
            wire_block = next(widget for message, widget in chat.message_history.rows
                              if message.seq == sent.seq)
            assert isinstance(wire_block, IRCMessage)
            assert len(wire_block.query(MessageDivider)) == 1
            expected_time = time.strftime("%H:%M:%S", time.localtime(sent.timestamp))
            inbound_divider = wire_block.query_one(MessageDivider)
            wire_block.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            assert expected_time in inbound_divider.render().plain, (
                expected_time, inbound_divider.clock, inbound_divider.size.width,
                inbound_divider.render().plain,
            )
            assert "Inbound" in wire_block.query_one(MessageDivider).render().plain
            outgoing_block = next(widget for message, widget in chat.message_history.rows
                                  if message.seq == outbound.seq)
            assert "Outbound" in outgoing_block.query_one(MessageDivider).render().plain
            await chat.message_history.toggle_style()
            await pilot.pause()
            wire_block = next(widget for message, widget in chat.message_history.rows
                              if message.seq == sent.seq)
            assert isinstance(wire_block, WireMarkdownMessage)
            assert len(wire_block.query(MessageDivider)) == 1
            assert len(wire_block.query(AgentResponse)) == 1
            assert len(wire_block.query(AgentResponse).first().query(MessageDivider)) == 0
            assert expected_time in wire_block.query_one(MessageDivider).render().plain
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("timestamped full-width user, inbound, agent and IRC/Markdown dividers; no thought divider")


if __name__ == "__main__":
    import sys
    asyncio.run(row_publication() if "--row-publication" in sys.argv else main())
