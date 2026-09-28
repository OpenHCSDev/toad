"""Mounted notification feedback: bounded batch, changing state, no hidden polling."""

import asyncio
import os
import tempfile
from pathlib import Path
from threading import Event, get_ident
from unittest.mock import patch

from agent_comms.comms import wire
from agent_comms.presentation import MessageNotification
from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.threads import Thread
from textual.screen import Screen

from runtime_fixture import ToadApp
from toad import messages
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.message_notifications import MessageNotifications
from toad.widgets.observed_thread_activity import ObservedThreadActivity


async def until(predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await asyncio.sleep(.02)


async def main():
    with tempfile.TemporaryDirectory(prefix="notification-pilot-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        comms.threads.register(Thread("peer", frozenset({"comms"}), str(root), pid=os.getpid()))
        for n in range(30):
            comms.messaging.send("peer", "#comms", f"Test {n}: " + "body " * 12)
        app = ToadApp(project_dir=str(root))
        calls, loop_thread = [], get_ident()
        state, priority, busy, failure = "Checking relevance…", 0, True, False
        gate, entered = Event(), Event()
        gate.set()

        def read(_self, batch):
            assert get_ident() != loop_thread
            calls.append(tuple(m.view_key for m in batch))
            entered.set()
            assert gate.wait(10), "fixture release missing"
            if failure:
                raise OSError("fixture busy database")
            return {(m.seq, m.message_id): (
                MessageNotification("active", state, "#comms message", priority, busy),
                *(MessageNotification(f"waiting-{n}", "Waiting for agent", "Not running", 4, False) for n in range(44)),
            ) for m in batch}

        with patch.object(type(comms.views), "message_notifications", read):
            async with app.run_test(size=(110, 40)) as pilot:
                await pilot.pause()
                native = app.screen.conversation
                native_mode = app.current_mode
                observed = native.query_one(ObservedThreadActivity)
                current = ThreadPresentation("peer", "●", "Checking #comms message", True)

                async def observe():
                    return current

                observed.read = observe
                observed.refresh_observation()
                await until(lambda: observed.presentation == current)
                native.post_message(messages.SessionUpdate(state="idle", summary="Ready"))
                await pilot.pause()
                tracker = app.session_tracker.sessions[native_mode]
                assert tracker.state == "busy" and "Checking #comms" in tracker.summary, tracker
                assert native._managed_turn_id is None and native.turn != "agent"
                current = ThreadPresentation("peer", "●", "Responding in #comms", True)
                observed.refresh_observation()
                await until(lambda: observed.presentation == current)
                await pilot.pause()
                assert "Responding in #comms" in tracker.summary

                await app.open_comms_session(owner_mode=native_mode, project_path=root,
                                             me="peer", target="#comms", kind="channel")
                chat = app.screen.query_one(CommsChatView)
                await until(lambda: chat._history_initialized and not chat._refresh_lock.locked()
                            and not chat._edge_load_scheduled)
                await pilot.pause()
                chat._refresh_notifications()
                await until(lambda: chat._notification_task is not None and chat._notification_task.done())
                feedback = next(w.query_one(MessageNotifications) for m, w in reversed(chat._history)
                                if m.view_key in chat._painted_message_keys())
                assert str(feedback.title).startswith("Checking relevance… (1)"), feedback.title
                assert 0 < len(calls[-1]) <= len(chat._history) <= 120
                assert set(calls[-1]) <= {m.view_key for m, _ in chat._visible_notification_rows()}
                await pilot.click(feedback.query_one("CollapsibleTitle"))
                await pilot.pause()
                assert not feedback.collapsed and "active: Checking relevance…" in str(feedback.details.render())
                feedback.collapsed = True
                feedback.parent.scroll_visible(animate=False, immediate=True, top=True)
                await pilot.pause()
                # Same bus revision, changed native lifecycle: the observation timer must refresh.
                state, priority, busy = "Responding…", 1, True
                try:
                    await until(lambda: "Responding…" in str(feedback.title))
                except TimeoutError:
                    print("DEBUG", {"title": str(feedback.title), "visible": chat._painted_message_keys(), "calls": calls[-4:], "lock": chat._refresh_lock.locked(), "task": repr(chat._notification_task), "scroll": (chat.window.scroll_y, chat.window.max_scroll_y), "attached": feedback.is_attached}, flush=True)
                    raise
                state, priority, busy = "Checked — no response", 2, False
                await until(lambda: str(feedback.title).startswith("Checked — no response (1)"))
                failure = True
                await until(lambda: "unavailable" in str(feedback.title))
                assert "fixture busy database" in str(feedback.details.render())
                failure, state, priority, busy = False, "Responded", 2, False
                await until(lambda: str(feedback.title).startswith("Responded (1)"))
                # One in-flight batch; hiding during a read must discard its result and stop polls.
                entered.clear(); gate.clear()
                chat._refresh_notifications()
                await until(entered.is_set)
                count = len(calls)
                chat._refresh_notifications(); chat._refresh_notifications()
                assert len(calls) == count
                await app.push_screen(Screen())
                gate.set()
                await until(lambda: chat._notification_task.done())
                for _ in range(3):
                    chat._refresh_notifications()
                    await chat._refresh()
                assert len(calls) == count
                app.pop_screen()
                await pilot.pause()
                # Markdown uses the same feedback owner and retains its separate body read proof.
                await chat.toggle_message_style()
                await pilot.pause()
                chat._refresh_notifications()
                await until(lambda: chat._notification_task.done())
                row = chat._history[-1][1]
                assert not isinstance(row.read_ack_widget(), MessageNotifications)
                assert "Responded" in str(row.query_one(MessageNotifications).title)
                row.query_one(MessageNotifications).show_result(())
                assert "No recorded" in str(row.query_one(MessageNotifications).title)
        await asyncio.get_running_loop().shutdown_default_executor()
        print("PASS: mounted IRC/Markdown, expanded details, live states without new messages, priority, batch/off-thread/visible bounds, errors/recovery, hidden/inflight guards, native Ready override, no fabricated ACP turn")


if __name__ == "__main__":
    asyncio.run(main())
