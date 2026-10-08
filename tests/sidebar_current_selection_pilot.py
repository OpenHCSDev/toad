"""Two real sidebar projections of one private wire and selected session."""
import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms.comms import wire
from agent_comms.threads import Thread
from runtime_fixture import ToadApp, coordination_update
from toad.widgets.comms_sidebar import CommsSidebar, ChannelGroup
from toad.widgets.message_divider import MessageDivider, RecordedMessageClock
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.thread_comms import ThreadCommsSidebar


async def until(pilot, condition):
    async with asyncio.timeout(15):
        while not condition():
            await pilot.pause(.02)


async def right_tree(app, pilot):
    bar = app.selected_session.query_one('#thread-sidebar', SideBar)
    bar.reveal()
    await bar.wait_content_ready()
    tree = bar.query_one(ThreadCommsSidebar)
    tree.query_ancestor(SideBarCollapsible).collapsed = False
    await until(pilot, lambda: 'outbound' in tree.groups and bool(tree.groups['outbound'].rows))
    return tree


async def main():
    scratch = Path('/home/ts/.cache/agent-scratch/sidebar-drag-hotpath-20261007')
    with tempfile.TemporaryDirectory(prefix='highlight-fixture-', dir=scratch) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        comms = wire(root / 'wire')
        for name in ('actor', 'peer-one', 'peer-two'):
            comms.registry.declare(Thread(name, frozenset({'team'}), str(root)))
        comms.messaging.send('peer-one', 'actor', 'Private incoming message')
        comms.messaging.send('actor', '#team', 'Private channel message')
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(140, 46)) as pilot:
            await app.selected_session.wait_content_ready()
            await app.selected_session.on_coordination_update(coordination_update(str(root / 'wire'), 'actor'))
            actor_mode = app.selected_mode
            channels = app.workspace_chrome.channels
            await channels.wait_content_ready()
            if not channels.collapsed:
                channels.toggle(focus=False)
            app.selected_session.action_focus_prompt()
            await pilot.press('ctrl+b')
            await until(pilot, lambda: not channels.collapsed and channels.has_focus_within)
            await app.workspace_chrome.channels.wait_content_ready()
            left = app.workspace_chrome.channels.query_one(CommsSidebar)
            await left.observation.sync()
            group = left.projection.channels['#team'].query_ancestor(ChannelGroup)
            await group.reveal_members()
            await until(pilot, lambda: left.navigation.ready.is_set() and len(group._members) == 3)
            assert group._members['actor'].current
            assert not group.row.current
            before = await right_tree(app, pilot)
            outgoing = next(row for row in before._ordered_rows() if row.target_name == '#team')
            assert not outgoing.current
            # Navigation comes through the actual row and real channel route.
            assert await pilot.click(group.row)
            await until(pilot, lambda: app.selected_mode != actor_mode)
            await app.selected_session.wait_content_ready()
            tree = await right_tree(app, pilot)
            if not channels.collapsed:
                channels.toggle(focus=False)
            app.selected_session.action_focus_prompt()
            await pilot.press('ctrl+b')
            await until(pilot, lambda: not channels.collapsed and channels.has_focus_within)
            assert app.screen.query_one('#channels-sidebar') is channels
            outgoing = next(row for row in tree._ordered_rows() if row.target_name == '#team')
            await until(pilot, lambda: group.row.current and outgoing.current)
            assert not app.sidebar_state.selected_targets
            assert not group.row.has_class('-selected')
            for theme in ('textual-dark', 'ansi-dark'):
                app.theme = theme
                await pilot.pause()
                assert group.row.styles.text_style.bold and outgoing.styles.text_style.bold
                assert group.row.styles.background.a == outgoing.styles.background.a == 0
                await pilot.hover(group.row)
                assert group.row.styles.text_style.bold and group.row.styles.text_style.underline
                first, second = group._members['peer-one'], group._members['peer-two']
                mode = app.selected_mode
                assert await pilot.click(first, control=True)
                assert await pilot.click(second, shift=True)
                assert app.selected_mode == mode
                assert first.selected and second.selected
                assert first.styles.background.a > 0
                assert group.row.current and outgoing.current
                left.remember_row(group.row)
                assert not app.sidebar_state.selected_targets
                assert not first.has_class('-selected')
                # The right tree uses the same range/toggle owner, preserving
                # its own relationship identity rather than channel pin scope.
                assert await pilot.click(outgoing, control=True)
                assert outgoing.selected and outgoing.current
                tree.remember_row(outgoing)
                assert not outgoing.selected and outgoing.current
            divider = MessageDivider('User', clock=RecordedMessageClock(1791374400))
            await app.selected_session.mount(divider)
            await pilot.pause()
            assert divider.clock[:10] in divider.render().plain
            assert len(divider.clock) == 19
            await app.select_session(actor_mode)
            await until(pilot, lambda: not group.row.current and group._members['actor'].current)
            assert app._exception is None
    print('PASS: active destination agrees in both bars; bulk/hover/focus remain distinct; date is visible; no provider inputs')


if __name__ == '__main__':
    asyncio.run(main())
