"""Original wire reads cannot borrow native receipt publication custody.

One actual application journey controls completion of its original source read;
all pages, registrations, messages, read witnesses and native rows remain real.
"""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.comms import wire
from runtime_fixture import ToadApp
from toad.navigation_target import NavigationContext, channel_target
from toad.widgets.comms_chat import CommsChatView


async def until(condition):
    async with asyncio.timeout(8):
        while not condition():
            await asyncio.sleep(.01)


async def pending_read(chat, pilot, send):
    """Control original read completion, never its decoded result or UI state."""
    history = chat.message_history
    reader = history.reader
    entered, release = asyncio.Event(), asyncio.Event()
    original = reader.read

    async def read(follow):
        result = await original(follow)
        entered.set()
        await release.wait()
        return result

    with patch.object(reader, 'read', read):
        refresh = asyncio.create_task(chat._refresh())
        try:
            await until(entered.is_set)
            assert not history.state.accepts_source_work
            assert not chat.window.history_lock.locked()
            receipt = send()
            await asyncio.wait_for(history.paint_receipt(receipt), 2)
            await pilot.pause()
            assert [m.view_key for m, _ in history.rows].count(receipt.view_key) == 1
            widget = next(w for m, w in history.rows if m.view_key == receipt.view_key)
            assert widget.is_attached and widget in chat.screen._compositor.visible_widgets
            chat.prompt.focus()
            await pilot.press('h', 'i')
            assert chat.prompt.text.endswith('hi')
        finally:
            release.set()
            await refresh
        await pilot.pause()
        assert [m.view_key for m, _ in history.rows].count(receipt.view_key) == 1
        assert not chat.window.history_lock.locked()


async def main():
    scratch = Path(__file__).resolve().parents[1] / '.artifacts' / 'history-lifetime338'
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='private-', dir=scratch) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'), XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'), XDG_DATA_HOME=str(root / 'data'))
        comms = wire(root / 'wire')
        comms.registry.declare(Thread('edge-reader', frozenset({'edge'}), str(root),
                                     process_identity=ProcessIdentity.capture(os.getpid())))
        for index in range(140):
            comms.messaging.send('edge-reader', '#edge', f'History {index}: ' + 'body ' * 40)
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            owner = app.selected_mode
            await channel_target('#edge').open(NavigationContext(app, owner, root, 'edge-reader'))
            chat = app.screen.query_one(CommsChatView)
            history = chat.message_history
            await until(lambda: history.checkpoint_available and bool(history.rows))
            await pilot.pause()
            assert history in chat.window.histories
            # Tail replacement started from the original initial source. An
            # already-painted later receipt survives its older read watermark.
            history.reader.restart()
            await pending_read(chat, pilot, lambda: comms.messaging.send(
                'edge-reader', '#edge', 'RECEIPT-DURING-TAIL-READ'))

            # Actual earlier pages evict the original tail. A send from that
            # reader position restarts the source and rejects the older read.
            operation = history.reserve_source_work()
            try:
                chat.window.release_anchor()
                while not history.has_newer:
                    page = await history.reader.page(before=history.rows[0][0].view_cursor, limit=40)
                    await history.mount_page(page, older=True)
            finally:
                history.finish_source_work(operation)
            assert history.has_newer
            history.reader.restart()
            await pending_read(chat, pilot, lambda: comms.messaging.send(
                'edge-reader', '#edge', 'RECEIPT-REVOKES-ORIGINAL-READ'))
            await until(lambda: history.checkpoint_available)
            assert history.rows[-1][0].body == 'RECEIPT-REVOKES-ORIGINAL-READ'

            chat.window.release_anchor()
            chat.window.scroll_home(animate=False, immediate=True)
            await until(lambda: history.has_newer)
            chat.window.jump_to_latest()
            await until(lambda: history.checkpoint_available and not history.has_newer)
            assert history.rows[-1][0].body == 'RECEIPT-REVOKES-ORIGINAL-READ'
            assert chat.window.follows_tail and app._exception is None
        assert not history.reader._pending
    print('PASS: original read admission, independent receipt paint, typing, restart fence, shared End and closed I/O')


if __name__ == '__main__':
    asyncio.run(main())
