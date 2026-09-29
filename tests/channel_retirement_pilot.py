"""Mounted migrated audience: normal sidebar/history and an explicit read-only composer."""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from agent_comms.comms import wire
from agent_comms.catalog_document import CatalogDocument, ChannelPreferences
from agent_comms.channels import AnyOfMatch, SavedView, ViewKind, ViewPredicate
from agent_comms.messages import Message, MessageType
from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from runtime_fixture import ToadApp
from toad import messages
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar


async def main():
    with tempfile.TemporaryDirectory(prefix="channel-retirement-", dir=os.environ['TMPDIR']) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'), XDG_CONFIG_HOME=str(root/'config'),
                          XDG_STATE_HOME=str(root/'state'), XDG_DATA_HOME=str(root/'data'))
        comms = wire(root/'wire')
        for name, tags in ((root.name, set()), ('api-agent', {'api'}), ('ui-agent', {'ui'})):
            comms.registry.declare(Thread(name, frozenset(tags), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
        rows = [comms.messaging.send_message('api-agent', target, body)
                for target, body in (('#engineering', 'original union message'),
                    ('#api', 'current exact message'), ('#engineering', 'another original message'))]
        comms.channels.catalog.replace(CatalogDocument(
            tags=frozenset({'api', 'ui'}),
            preferences={'#engineering': ChannelPreferences(pinned=True, created_at=17)},
            saved_views={'engineering': SavedView('engineering', ViewKind.ACTIVITY,
                ViewPredicate(AnyOfMatch, frozenset({'api','ui'})), 17,
                frozenset({'#engineering'}))},
        ))
        original = comms.bus.log.path.read_bytes()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110,35)) as pilot:
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)
            async with asyncio.timeout(8):
                while '#engineering' not in {g.row.target_name for g in sidebar.query(ChannelGroup)}:
                    await pilot.pause(.05)
            group = next(g for g in sidebar.query(ChannelGroup) if g.row.target_name == '#engineering')
            group.row.focus()
            await pilot.press("enter")
            await pilot.pause()
            chat = app.screen.query_one(CommsChatView)
            await chat._refresh()
            await pilot.pause()
            assert [m.body for m,_ in chat.message_history.rows] == [m.body for m in rows]
            assert chat.prompt.prompt_text_area.disabled
            assert 'Read-only' in chat.status
            await chat.submit_input(messages.UserInputSubmitted('must not publish'))
            assert chat.prompt.text == 'must not publish'
            assert comms.bus.log.path.read_bytes() == original
            assert next(v for v in comms.views.channel_views() if v.channel.name=='#engineering').channel.pinned
        await asyncio.get_running_loop().shutdown_default_executor()
    print('PASS mounted sidebar, original/exact history, preserved pin, disabled composer, rejected direct submit, unchanged bus')


if __name__ == '__main__':
    asyncio.run(main())
