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

async def until(predicate):
    async with asyncio.timeout(12):
        while not predicate():
            await asyncio.sleep(.02)

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
            await until(lambda: chat.message_history.initialized and not chat.message_history.lock.locked())
            await channel_target('#two').open(NavigationContext(app, owner, root, 'peer'))
            await pilot.pause()
            # Mark current page loaded before instrumenting the hidden reader.
            await until(lambda: not chat.message_history.lock.locked() and not chat.message_history.ack_inflight)
            comms.messaging.send('peer', '#one', 'ARRIVED-WHILE-HIDDEN')
            with patch('toad.comms_root.root_is_current', side_effect=AssertionError('hidden route check')):
                # Exercise the real hidden callback, not a mocked visibility test.
                for _ in range(40):
                    await chat._refresh()
                assert not any(m.body == 'ARRIVED-WHILE-HIDDEN' for m,_ in chat.message_history.rows)
            await app.switch_mode(first)
            await until(lambda: any(m.body == 'ARRIVED-WHILE-HIDDEN' for m,_ in chat.message_history.rows))
            assert app._exception is None
        assert not app.channel_history_reader._pending
    print('PASS: hidden channel refresh has no root check/history query; resumed window fetches current message')

if __name__ == '__main__':
    asyncio.run(main())
