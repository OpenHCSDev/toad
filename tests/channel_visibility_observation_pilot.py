"""Only current channel windows read; resuming fetches current data, never a warm stale page."""
from toad.navigation_target import NavigationContext

from toad.navigation_target import channel_target
import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from agent_comms.comms import wire
from agent_comms.threads import Thread
from runtime_fixture import ToadApp
from toad.widgets.comms_chat import CommsChatView
from toad.channel_preparation import ChannelHistoryReader
from runtime_fixture import refresh_comms

async def until(predicate):
    async with asyncio.timeout(12):
        while not predicate():
            await asyncio.sleep(.02)

async def checkpoint_checks(app, pilot, comms, root, checks):
    """Borrow the original registered channel leaf in an existing App."""
    comms.registry.declare(Thread('checkpoint-peer', frozenset({'checkpoint'}), str(root)))
    comms.messaging.send('checkpoint-peer', '#checkpoint', 'ORIGINAL_CHECKPOINT_ROW')
    actor = comms.messaging.user_identity(str(root)).name
    entered, release = asyncio.Event(), asyncio.Event()
    original_read = ChannelHistoryReader.read
    worker = None

    async def pending_read(reader, follow_tail):
        if reader.source.target == '#checkpoint' and reader.source.loading:
            entered.set()
            await release.wait()
        return await original_read(reader, follow_tail)

    with patch.object(ChannelHistoryReader, 'read', pending_read):
        try:
            await channel_target('#checkpoint').open(NavigationContext(
                app, app.selected_mode, root, actor,
            ))
            await until(entered.is_set)
            chat = app.screen.query_one(CommsChatView)
            history = chat.message_history
            reader, window = history.reader, chat.window
            checks['wire_original_reader_loading_blocks_checkpoint'] = (
                history.is_attached and history in window.histories
                and reader.source.loading and not history.source_checkpoint_available
                and not history.checkpoint_available and history.blocks_visible_read)
            checks['wire_original_read_admission_blocks_checkpoint'] = (
                not history.state.accepts_source_work and history.blocks_visible_read)
            release.set()
            await until(lambda: history.state.accepts_source_work and not reader.source.loading)
            checks['wire_accepted_reader_live_checkpoint_available'] = (
                history.reader is reader and history.source_checkpoint_available
                and history.checkpoint_available and not history.has_newer
                and not history.blocks_visible_read
                and [message.body for message, _ in history.rows] == ['ORIGINAL_CHECKPOINT_ROW'])

            # The actual reader's restart creates its original loading request.
            # Source state remains Live until the real refresh admits its worker.
            entered.clear()
            release.clear()
            reader.restart()
            checks['wire_live_loading_resource_revokes_checkpoint'] = (
                history.state.accepts_source_work and reader.source.loading
                and not history.source_checkpoint_available
                and not history.checkpoint_available and history.blocks_visible_read)
            worker = await chat._refresh()
            await until(entered.is_set)
            checks['wire_restart_read_admission_owns_checkpoint'] = (
                worker is not None and not history.state.accepts_source_work
                and not history.checkpoint_available and history.blocks_visible_read)
            release.set()
            await worker.wait()
            checks['wire_restart_completion_restores_checkpoint'] = (
                history.reader is reader and not reader.source.loading
                and history.checkpoint_available and not history.blocks_visible_read)
            assert all(checks.values()), checks
            return history, reader, window, history._task
        finally:
            release.set()
            if worker is not None:
                await worker.wait()

async def main():
    with tempfile.TemporaryDirectory(prefix='channel-visible-') as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'), XDG_CONFIG_HOME=str(root/'config'),
                          XDG_STATE_HOME=str(root/'state'), XDG_DATA_HOME=str(root/'data'))
        comms = wire(root/'wire')
        comms.registry.declare(Thread('peer', frozenset({'one', 'two'}), str(root)))
        comms.messaging.send('peer', '#one', 'FIRST')
        comms.messaging.send('peer', '#two', 'SECOND')
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100,35)) as pilot:
            await pilot.pause()
            owner = app.selected_mode
            first = await channel_target('#one').open(NavigationContext(app, owner, root, 'peer'))
            chat = app.screen.query_one(CommsChatView)
            await until(lambda: (chat.message_history.reader is not None and not chat.message_history.reader.source.loading) and chat.message_history.state.accepts_source_work)
            await channel_target('#two').open(NavigationContext(app, owner, root, 'peer'))
            await pilot.pause()
            # Mark current page loaded before instrumenting the hidden reader.
            await until(lambda: chat.message_history.state.accepts_source_work and not chat.message_history.ack_inflight)
            comms.messaging.send('peer', '#one', 'ARRIVED-WHILE-HIDDEN')
            with patch('toad.comms_root.root_is_current', side_effect=AssertionError('hidden route check')):
                # Exercise the real hidden callback, not a mocked visibility test.
                for _ in range(40):
                    await refresh_comms(chat)
                assert not any(m.body == 'ARRIVED-WHILE-HIDDEN' for m,_ in chat.message_history.rows)
            await app.switch_mode(first)
            await until(lambda: any(m.body == 'ARRIVED-WHILE-HIDDEN' for m,_ in chat.message_history.rows))
            assert app._exception is None
        assert not chat.message_history.reader._pending
    print('PASS: hidden channel refresh has no root check/history query; resumed window fetches current message')

if __name__ == '__main__':
    asyncio.run(main())
