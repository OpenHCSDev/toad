"""History paging must wait for refresh completion without callback churn."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
from threading import Event
import time
from unittest.mock import patch

from agent_comms import MessagePage, Thread, wire

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
        comms.register(Thread("edge-reader", frozenset({"edge"}), str(root), pid=os.getpid()))
        for index in range(60):
            comms.send("edge-reader", "#edge", f"History {index}: " + "body " * 40)
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            mode = await app.open_comms_session(owner_mode=owner, project_path=root,
                                                me="edge-reader", target="#edge", kind="channel")
            chat = app.screen.query_one(CommsChatView)
            await until(lambda: chat._history_initialized and not chat._refresh_lock.locked()
                        and not chat._edge_load_scheduled)
            await pilot.pause()
            assert chat._has_older and chat.window.max_scroll_y > 0
            oldest = chat._history[0][0].seq
            attempts = 0
            original = chat._load_history_edge

            async def counted_edge_load():
                nonlocal attempts
                attempts += 1
                await original()

            held = True
            await chat._refresh_lock.acquire()
            try:
                with patch.object(chat, "_load_history_edge", counted_edge_load):
                    chat.window.release_anchor()
                    chat.window.scroll_to(y=0, animate=False, immediate=True)
                    chat._on_window_scroll()
                    started = time.thread_time()
                    wall = time.monotonic()
                    await asyncio.sleep(.25)
                    cpu = time.thread_time() - started
                    blocked_attempts = attempts
                    print(json.dumps({"gate_seconds": round(time.monotonic() - wall, 3),
                                      "edge_attempts_while_locked": blocked_attempts,
                                      "ui_thread_cpu_ms": round(cpu * 1000, 2)}))
                    assert chat._history[0][0].seq == oldest
                    assert blocked_attempts <= 1, "History-edge retries churn while refresh owns the lock"
                    chat.prompt.focus()
                    await pilot.press("h", "i")
                    assert chat.prompt.text == "hi", "A lock waiter held the widget message pump"
                    chat._refresh_lock.release()
                    held = False
                    await until(lambda: chat._history[0][0].seq < oldest)
                    await until(lambda: not chat._edge_load_scheduled)
            finally:
                if held:
                    chat._has_older = chat._has_newer = False
                    chat._refresh_lock.release()

            assert chat._has_older and chat.window.max_scroll_y > 10
            # A duplicate or empty page with unchanged cursors/flags cannot
            # autonomously rearm. A later actual scroll can request a retry.
            for duplicate in (False, True):
                chat.window.scroll_to(y=10, animate=False, immediate=True)
                await pilot.pause()
                page = MessagePage(tuple(message for message, _ in chat._history[:2]) if duplicate else (), True, False)
                with patch.object(chat, "_message_page", return_value=page) as reads:
                    chat.window.scroll_to(y=0, animate=False, immediate=True)
                    chat._on_window_scroll()
                    await until(lambda: reads.call_count > 0 and not chat._edge_load_scheduled)
                    await asyncio.sleep(.15)
                    assert reads.call_count == 1, "No-progress page caused repeated reads"

            chat.window.scroll_to(y=10, animate=False, immediate=True)
            await pilot.pause()
            with patch.object(chat, "_message_page", side_effect=OSError("blocked fixture source")) as reads:
                chat.window.scroll_to(y=0, animate=False, immediate=True)
                chat._on_window_scroll()
                await until(lambda: reads.call_count > 0 and not chat._edge_load_scheduled)
                await asyncio.sleep(.15)
                assert reads.call_count == 1, "Failed page caused automatic retry churn"

            # A waiting request uses the latest viewport when the lock opens.
            chat.window.scroll_to(y=10, animate=False, immediate=True)
            await pilot.pause()
            await chat._refresh_lock.acquire()
            held = True
            try:
                with patch.object(chat, "_message_page", wraps=chat._message_page) as reads:
                    chat.window.scroll_to(y=0, animate=False, immediate=True)
                    chat._on_window_scroll()
                    await asyncio.sleep(.04)
                    chat.window.scroll_to(y=10, animate=False, immediate=True)
                    chat._refresh_lock.release()
                    held = False
                    await until(lambda: not chat._edge_load_scheduled)
                    reads.assert_not_called()
            finally:
                if held:
                    chat._refresh_lock.release()

            # Scroll to the other edge during a blocked request: load the latest
            # requested direction rather than the one captured at queue time.
            await chat._refresh_lock.acquire()
            held = True
            try:
                with patch.object(chat, "_message_page", return_value=MessagePage((), True, False)) as reads:
                    chat.window.scroll_to(y=0, animate=False, immediate=True)
                    chat._on_window_scroll()
                    await asyncio.sleep(.04)
                    chat._has_newer = True
                    chat.window.scroll_end(animate=False, immediate=True)
                    newest = chat._history[-1][0].seq
                    chat._refresh_lock.release()
                    held = False
                    await until(lambda: reads.call_count > 0 and not chat._edge_load_scheduled)
                    assert reads.call_count == 1 and reads.call_args.kwargs == {"after": newest}
            finally:
                if held:
                    chat._refresh_lock.release()

            # Tab exit while a queued request waits performs no hidden page read;
            # returning still completes the needed load without another scroll.
            oldest = chat._history[0][0].seq
            await chat._refresh_lock.acquire()
            held = True
            try:
                with patch.object(chat, "_message_page", wraps=chat._message_page) as reads:
                    chat.window.release_anchor()
                    chat.window.scroll_to(y=0, animate=False, immediate=True)
                    chat._on_window_scroll()
                    await asyncio.sleep(.04)
                    await asyncio.wait_for(app.switch_mode(owner), 2)
                    chat._refresh_lock.release()
                    held = False
                    await until(lambda: not chat._edge_load_scheduled)
                    reads.assert_not_called()
                    await app.switch_mode(mode)
                    await until(lambda: chat._history[0][0].seq < oldest)
                    await until(lambda: not chat._edge_load_scheduled)
            finally:
                if held:
                    chat._refresh_lock.release()
            assert chat.prompt.text == "hi"

            # Delayed IO finishing after tab exit must not mount into a hidden
            # history transaction (which cannot get a current-screen layout).
            entered, release = Event(), Event()
            records = tuple(message.seq for message, _ in chat._history)
            chat._has_older = True
            original_page = chat._message_page

            def delayed_page(*args, **kwargs):
                entered.set()
                if not release.wait(8):
                    raise TimeoutError("Test did not release edge read")
                return original_page(*args, **kwargs)

            try:
                with patch.object(chat, "_message_page", delayed_page):
                    chat.window.scroll_to(y=0, animate=False, immediate=True)
                    chat._on_window_scroll()
                    assert await asyncio.to_thread(entered.wait, 2)
                    await app.switch_mode(owner)
                    release.set()
                    await until(lambda: not chat._edge_load_scheduled)
                    assert tuple(message.seq for message, _ in chat._history) == records
                    assert not chat.window.history_lock.locked()
            finally:
                release.set()

            await app.switch_mode(mode)
            await until(lambda: not chat._edge_load_scheduled and not chat._refresh_lock.locked())
            await chat._refresh_lock.acquire()
            try:
                chat._has_older = True
                chat.window.scroll_to(y=0, animate=False, immediate=True)
                chat._on_window_scroll()
                await asyncio.sleep(.04)
                await asyncio.wait_for(app.close_session_mode(mode), 2)
                await until(lambda: not chat._edge_load_scheduled)
            finally:
                chat._refresh_lock.release()

            await pilot.resize_terminal(100, 80)
            comms.set_channel("#short", frozenset({"edge"}))
            for index in range(12):
                comms.send("edge-reader", "#short", f"Small {index}")
            await app.open_comms_session(owner_mode=owner, project_path=root,
                                         me="edge-reader", target="#short", kind="channel")
            short = app.screen.query_one(CommsChatView)
            await until(lambda: len(short._history) == 12 and not short._edge_load_scheduled)
            assert not short._has_older and app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("history-edge scheduling: bounded wait, typing, no-progress/error, latest viewport, tab return, late IO, close and underfill OK")


if __name__ == "__main__":
    asyncio.run(main())
