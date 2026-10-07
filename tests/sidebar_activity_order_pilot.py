"""Changed and retained native rows preserve the canonical channel order."""

import asyncio
import os
from pathlib import Path

from agent_comms.activity import ActivityState
from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import Comms
from agent_comms.display_order import ThreadSort
from agent_comms.threads import Thread
from runtime_fixture import ToadApp, wait_channel_roster
from toad.widgets.comms_sidebar import ChannelGroup


async def main():
    root = Path(os.environ['SIDEBAR_ACTIVITY_ARTIFACTS']).resolve()
    root.mkdir(parents=True, exist_ok=False)
    os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                      XDG_CONFIG_HOME=str(root / 'config'),
                      XDG_STATE_HOME=str(root / 'state'),
                      XDG_DATA_HOME=str(root / 'data'))
    comms = Comms(root / 'wire')
    comms.messaging.initialize_private_initial_protocol()
    for name in ('pinned', 'older', 'recent'):
        comms.registry.declare(Thread(name, frozenset({'team'}), str(root),
            process_identity=ProcessIdentity.capture(os.getpid())))
    comms.channels.set_thread_pinned('#team', 'pinned', True)
    comms.channels.set_channel_sort('#team', ThreadSort.LAST_ACTIVITY)
    comms.agents.set_activity('recent', ActivityState.IDLE)
    comms.agents.set_activity('older', ActivityState.IDLE)
    app = ToadApp(project_dir=str(root))
    async with app.run_test(size=(130, 45)) as pilot:
        await app.selected_session.wait_content_ready()
        sidebar = await wait_channel_roster(app, pilot, '#team')
        group = next(group for group in sidebar.query(ChannelGroup)
                     if group.row.target_name == '#team')
        await group.reveal_members()
        await pilot.pause()
        original = dict(group._members)
        unchanged = original['older']._thread_presentation
        assert tuple(row.target_name for row in group.member_container.children) == (
            'pinned', 'older', 'recent')

        # Actual backend activity changes both ordering and the prepared status
        # of one row; the other rows retain their original render resources.
        comms.agents.set_activity('recent', ActivityState.WORKING, 'Reading source')
        await sidebar.observation.sync()
        await pilot.pause()
        expected = next(view.members for view in sidebar.projection.snapshot.wire.channels
                        if view.channel.name == '#team')
        actual = tuple(row.target_name for row in group.member_container.children)
        assert expected == ('pinned', 'recent', 'older'), expected
        assert actual == expected, (expected, actual)
        assert group._members == original
        assert original['older']._thread_presentation is unchanged
        assert original['recent']._thread_presentation.source.busy
        assert app._exception is None
        print('Actual activity moved the changed native row ahead of the retained row; '
              'pin, widget identity and unchanged paint resource preserved.', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
