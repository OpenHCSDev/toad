"""History paging must wait for refresh completion without callback churn."""
from toad.navigation_target import NavigationContext

from toad.navigation_target import channel_target

import asyncio
import json
import os
from pathlib import Path
import tempfile
from threading import Event
import time
from unittest.mock import patch

from agent_comms.message_page import MessagePage
from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.comms import wire

from runtime_fixture import ToadApp
from toad.widgets.comms_chat import CommsChatView


async def until(condition):
    async with asyncio.timeout(8):
        while not condition():
            await asyncio.sleep(.01)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-edge-scheduling-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        comms.registry.declare(Thread("edge-reader", frozenset({"edge"}), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
        for index in range(60):
            comms.messaging.send("edge-reader", "#edge", f"History {index}: " + "body " * 40)
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            owner = app.selected_mode
            mode = await channel_target("#edge").open(NavigationContext(app, owner, root, "edge-reader"))
            chat = app.screen.query_one(CommsChatView)
            await until(lambda: chat.message_history.initialized and not chat.message_history.lock.locked()
                        and not chat.message_history.edge_scheduled)
            await pilot.pause()
            assert chat.message_history.has_older and chat.window.max_scroll_y > 0
            oldest = chat.message_history.rows[0][0].seq
            attempts = 0
            original = chat.message_history.load_edge

            async def counted_edge_load():
                nonlocal attempts
                attempts += 1
                await original()

            held = True
            await chat.message_history.lock.acquire()
            try:
                with patch.object(chat.message_history, "load_edge", counted_edge_load):
                    chat.window.release_anchor()
                    chat.window.scroll_to(y=0, animate=False, immediate=True)
                    chat.message_history.on_scroll()
                    started = time.thread_time()
                    wall = time.monotonic()
                    await asyncio.sleep(.25)
                    cpu = time.thread_time() - started
                    blocked_attempts = attempts
                    print(json.dumps({"gate_seconds": round(time.monotonic() - wall, 3),
                                      "edge_attempts_while_locked": blocked_attempts,
                                      "ui_thread_cpu_ms": round(cpu * 1000, 2)}))
                    assert chat.message_history.rows[0][0].seq == oldest
                    assert blocked_attempts <= 1, "History-edge retries churn while refresh owns the lock"
                    chat.prompt.focus()
                    await pilot.press("h", "i")
                    assert chat.prompt.text == "hi", "A lock waiter held the widget message pump"
                    chat.message_history.lock.release()
                    held = False
                    await until(lambda: chat.message_history.rows[0][0].seq < oldest)
                    await until(lambda: not chat.message_history.edge_scheduled)
            finally:
                if held:
                    chat.message_history.has_older = chat.message_history.has_newer = False
                    chat.message_history.lock.release()

            assert chat.message_history.has_older and chat.window.max_scroll_y > 10
            # A duplicate or empty page with unchanged cursors/flags cannot
            # autonomously rearm. A later actual scroll can request a retry.
            for duplicate in (False, True):
                chat.window.scroll_to(y=10, animate=False, immediate=True)
                await pilot.pause()
                page = MessagePage(tuple(message for message, _ in chat.message_history.rows[:2]) if duplicate else (), True, False)
                with patch.object(chat.message_history, "read_page", return_value=page) as reads:
                    chat.window.scroll_to(y=0, animate=False, immediate=True)
                    chat.message_history.on_scroll()
                    await until(lambda: reads.call_count > 0 and not chat.message_history.edge_scheduled)
                    await asyncio.sleep(.15)
                    assert reads.call_count == 1, "No-progress page caused repeated reads"

            chat.window.scroll_to(y=10, animate=False, immediate=True)
            await pilot.pause()
            with patch.object(chat.message_history, "read_page", side_effect=OSError("blocked fixture source")) as reads:
                chat.window.scroll_to(y=0, animate=False, immediate=True)
                chat.message_history.on_scroll()
                await until(lambda: reads.call_count > 0 and not chat.message_history.edge_scheduled)
                await asyncio.sleep(.15)
                assert reads.call_count == 1, "Failed page caused automatic retry churn"

            # A waiting request uses the latest viewport when the lock opens.
            chat.window.scroll_to(y=10, animate=False, immediate=True)
            await pilot.pause()
            await chat.message_history.lock.acquire()
            held = True
            try:
                with patch.object(chat.message_history, "read_page", wraps=chat.message_history.read_page) as reads:
                    chat.window.scroll_to(y=0, animate=False, immediate=True)
                    chat.message_history.on_scroll()
                    await asyncio.sleep(.04)
                    chat.window.scroll_to(y=10, animate=False, immediate=True)
                    chat.message_history.lock.release()
                    held = False
                    await until(lambda: not chat.message_history.edge_scheduled)
                    reads.assert_not_called()
            finally:
                if held:
                    chat.message_history.lock.release()

            # Scroll to the other edge during a blocked request: load the latest
            # requested direction rather than the one captured at queue time.
            await chat.message_history.lock.acquire()
            held = True
            try:
                with patch.object(chat.message_history, "read_page", return_value=MessagePage((), True, False)) as reads:
                    chat.window.scroll_to(y=0, animate=False, immediate=True)
                    chat.message_history.on_scroll()
                    await asyncio.sleep(.04)
                    chat.message_history.has_newer = True
                    chat.window.scroll_end(animate=False, immediate=True)
                    newest = chat.message_history.rows[-1][0].seq
                    chat.message_history.lock.release()
                    held = False
                    await until(lambda: reads.call_count > 0 and not chat.message_history.edge_scheduled)
                    assert reads.call_count == 1 and reads.call_args.kwargs == {"after": newest}
            finally:
                if held:
                    chat.message_history.lock.release()

            # Tab exit while a queued request waits performs no hidden page read;
            # returning still completes the needed load without another scroll.
            oldest = chat.message_history.rows[0][0].seq
            await chat.message_history.lock.acquire()
            held = True
            try:
                with patch.object(chat.message_history, "read_page", wraps=chat.message_history.read_page) as reads:
                    chat.window.release_anchor()
                    chat.window.scroll_to(y=0, animate=False, immediate=True)
                    chat.message_history.on_scroll()
                    await asyncio.sleep(.04)
                    await asyncio.wait_for(app.switch_mode(owner), 2)
                    chat.message_history.lock.release()
                    held = False
                    await until(lambda: not chat.message_history.edge_scheduled)
                    reads.assert_not_called()
                    await app.switch_mode(mode)
                    await until(lambda: chat.message_history.rows[0][0].seq < oldest)
                    await until(lambda: not chat.message_history.edge_scheduled)
            finally:
                if held:
                    chat.message_history.lock.release()
            assert chat.prompt.text == "hi"

            # Delayed IO finishing after tab exit must not mount into a hidden
            # history transaction (which cannot get a current-screen layout).
            entered, release = Event(), Event()
            records = tuple(message.seq for message, _ in chat.message_history.rows)
            chat.message_history.has_older = True
            original_page = chat.message_history.read_page

            def delayed_page(*args, **kwargs):
                entered.set()
                if not release.wait(8):
                    raise TimeoutError("Test did not release edge read")
                return original_page(*args, **kwargs)

            try:
                with patch.object(chat.message_history, "read_page", delayed_page):
                    chat.window.scroll_to(y=0, animate=False, immediate=True)
                    chat.message_history.on_scroll()
                    assert await asyncio.to_thread(entered.wait, 2)
                    await app.switch_mode(owner)
                    release.set()
                    await until(lambda: not chat.message_history.edge_scheduled)
                    assert tuple(message.seq for message, _ in chat.message_history.rows) == records
                    assert not chat.window.history_lock.locked()
            finally:
                release.set()

            await app.switch_mode(mode)
            await until(lambda: not chat.message_history.edge_scheduled and not chat.message_history.lock.locked())
            await chat.message_history.lock.acquire()
            try:
                chat.message_history.has_older = True
                chat.window.scroll_to(y=0, animate=False, immediate=True)
                chat.message_history.on_scroll()
                await asyncio.sleep(.04)
                await asyncio.wait_for(app.session_navigation.close(mode), 2)
                await until(lambda: not chat.message_history.edge_scheduled)
            finally:
                chat.message_history.lock.release()

            await pilot.resize_terminal(100, 80)
            comms.channels.create_tag("short")
            for index in range(12):
                comms.messaging.send("edge-reader", "#short", f"Small {index}")
            await channel_target("#short").open(NavigationContext(app, owner, root, "edge-reader"))
            short = app.screen.query_one(CommsChatView)
            await until(lambda: len(short._history) == 12 and not short.message_history.edge_scheduled)
            assert not short.message_history.has_older and app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("history-edge scheduling: bounded wait, typing, no-progress/error, latest viewport, tab return, late IO, close and underfill OK")


if __name__ == "__main__":
    asyncio.run(main())
