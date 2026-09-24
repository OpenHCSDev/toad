"""Inactive open channels prefetch bounded data without painting or acknowledging."""

import asyncio
import os
from pathlib import Path
import tempfile
from threading import Event, get_ident
from unittest.mock import patch

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad.widgets.comms_chat import CommsChatView, session_thread_name


async def until(pilot, condition):
    async with asyncio.timeout(8):
        while not condition():
            await pilot.pause(.01)


async def main():
    with tempfile.TemporaryDirectory(prefix="channel-background-warmup-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        me = session_thread_name(root)
        comms.register(Thread(me, frozenset({"warm"}), str(root), pid=os.getpid()))
        comms.send(me, "#warm", "Initial history")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            mode = await app.open_comms_session(owner_mode=owner, project_path=root,
                                               me=me, target="#warm", kind="channel")
            chat = app.screen.query_one(CommsChatView)
            await until(pilot, lambda: chat._history_initialized and not chat._refresh_lock.locked())
            await until(pilot, lambda: comms.viewer_snapshot(str(root)).channel_unread["#warm"] == 0)
            await app.switch_mode(owner)
            comms.send(me, "#warm", "PREPARED-WHILE-HIDDEN")
            reader = chat._wire
            with (patch.object(reader, "mark_channel_view_read", wraps=reader.mark_channel_view_read) as mark,
                  patch.object(reader, "channel_display_page", wraps=reader.channel_display_page) as reads):
                await until(pilot, lambda: chat._prepared_history is not None
                            and chat._prepared_history.page is not None
                            and any(message.body == "PREPARED-WHILE-HIDDEN"
                                    for message in chat._prepared_history.page.messages))
                assert not any(message.body == "PREPARED-WHILE-HIDDEN" for message, _ in chat._history)
                mark.assert_not_called()
                assert comms.viewer_snapshot(str(root)).channel_unread["#warm"] == 1
                calls = reads.call_count
                await pilot.pause(.12)
                assert reads.call_count == calls, "Unchanged hidden history was reread"
                await app.switch_mode(mode)
                await until(pilot, lambda: any(message.body == "PREPARED-WHILE-HIDDEN" for message, _ in chat._history))
                assert reads.call_count == calls, "Activation reread an already-prepared page"
                assert chat.window.follows_tail

            # Source identity changes invalidate an old prepared page, rather
            # than importing another target's data into this view.
            await app.switch_mode(owner)
            comms.send(me, "#warm", "OLD-TARGET-PAGE")
            await until(pilot, lambda: chat._prepared_history is not None and chat._prepared_history.page is not None
                        and any(message.body == "OLD-TARGET-PAGE" for message in chat._prepared_history.page.messages))
            old = chat._prepared_history
            comms.set_channel("#other", frozenset({"other"}))
            chat.target = "#other"
            assert old.request != chat._history_request()
            chat.target = "#warm"

            # A blocked read that began while hidden stays off-loop when the tab
            # is selected. Typing and leaving the tab still work; late completion
            # warms data without acknowledging the newly received message.
            entered, release = Event(), Event()
            original_page = reader.channel_display_page
            main_thread = get_ident()

            def gated_page(target, **kwargs):
                assert get_ident() != main_thread
                entered.set()
                if not release.wait(6):
                    raise TimeoutError("Test did not release warm history read")
                return original_page(target, **kwargs)

            try:
                with patch.object(reader, "channel_display_page", side_effect=gated_page):
                    comms.send(me, "#warm", "BLOCKED-BACKGROUND-READ")
                    assert await asyncio.to_thread(entered.wait, 3)
                    await asyncio.wait_for(app.switch_mode(mode), 2)
                    await until(pilot, lambda: chat.throbber.busy)
                    chat.prompt.focus()
                    await pilot.press("h", "i")
                    assert chat.prompt.text == "hi"
                    await asyncio.wait_for(app.switch_mode(owner), 2)
                    release.set()
                    await until(pilot, lambda: chat._prepared_history is not None
                                and chat._prepared_history.page is not None
                                and any(message.body == "BLOCKED-BACKGROUND-READ"
                                        for message in chat._prepared_history.page.messages))
                    assert comms.viewer_snapshot(str(root)).channel_unread["#warm"] >= 1
                    assert not any(message.body == "BLOCKED-BACKGROUND-READ" for message, _ in chat._history)
            finally:
                release.set()

            # A warm read can finish while Textual is dismantling this view:
            # the view may still be attached after its Window child is gone.
            # Its completion callback must discard the page without a getter
            # exception or a read acknowledgement.
            late_result = chat._prepared_history
            assert late_result is not None
            completed = asyncio.create_task(asyncio.sleep(0, result=late_result))
            await completed
            chat._prepared_history = None
            await chat.window.remove()
            assert chat.is_attached
            chat._history_warmed(completed)
            assert chat._prepared_history is None
            assert app._exception is None
        assert not app.channel_history_reader._pending
        await asyncio.get_running_loop().shutdown_default_executor()
    print("channel warming: hidden bounded prefetch, no read ACK/DOM publication, no duplicate read on activation")


if __name__ == "__main__":
    asyncio.run(main())
