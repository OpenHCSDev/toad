"""Native small-terminal batch dialog and filter-independent channel counts."""
import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms.cli_commands import CliCommand, DeleteTagCliCommand
from agent_comms.channel_management import DeleteExclusiveInactiveThreadsTagDisposition
from agent_comms.field_codec import FieldCodec
from agent_comms.comms import Comms
from agent_comms.threads import Thread
from agent_comms.thread_status import IdleThreadStatus, StoppedThreadStatus
from runtime_fixture import ToadApp
from toad.target_commands import TargetContext
from toad.thread_actions import ThreadAction
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.comms_command_dialog import CommandDialog
from textual.containers import VerticalScroll
from textual.widgets import Button, Select, Static


async def until(pilot, condition):
    async with asyncio.timeout(20):
        while not condition():
            await pilot.pause(.02)


async def main():
    scratch = Path('/home/ts/.cache/agent-scratch/sidebar-drag-hotpath-20261007')
    with tempfile.TemporaryDirectory(prefix='tag-dialog-', dir=scratch) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        comms = Comms(root / 'wire', private_initial_writes=True)
        tags = tuple(f'group-{index:02}-long-channel-name' for index in range(30))
        for index, tag in enumerate(tags):
            comms.registry.declare(Thread(f'member-{index}', frozenset({tag}), str(root)),
                                   StoppedThreadStatus())
        comms.registry.declare(Thread('idle-member', frozenset({tags[0]}), str(root)),
                               IdleThreadStatus())
        comms.messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        app.settings.sidebar.show_stopped = False
        async with app.run_test(size=(85, 24)) as pilot:
            await app.selected_session.wait_content_ready()
            app.workspace_chrome.channels.reveal()
            await app.workspace_chrome.channels.wait_content_ready()
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar.observation.sync()
            await pilot.pause()
            row = sidebar.projection.channels['#' + tags[0]]
            assert str(row.content) == '#' + tags[0] + ' 1/2', row.content
            app.settings.sidebar.show_stopped = True
            await sidebar.observation.sync()
            await pilot.pause()
            assert str(row.content).endswith(' 1/2'), row.content
            targets = tuple('#' + tag for tag in tags)
            definition = next(action for action in await app.preparation.run_thread(
                lambda: CliCommand.target_catalog(comms, targets, project=str(root)))
                if action.declaration is DeleteTagCliCommand)
            context = TargetContext(app, comms, targets[0], 'fixture', root, targets=targets)
            ThreadAction.collect(context, definition)
            await until(pilot, lambda: isinstance(app.screen, CommandDialog) and app.screen.is_mounted)
            dialog = app.screen
            await until(pilot, lambda: not dialog.query_one('#command-apply', Button).disabled)
            select = dialog.query_one(Select)
            # The declared destructive option has one warning for all tags.
            select.value = FieldCodec.encode(DeleteExclusiveInactiveThreadsTagDisposition)
            await pilot.pause()
            await until(pilot, lambda: not dialog.query_one('#command-apply', Button).disabled)
            warning = str(dialog.query_one('#command-confirmation', Static).content)
            assert warning.count('Active owners, multitag threads') == 1, warning
            assert all('#' + tag in warning for tag in tags)
            body = dialog.query_one('#command-body', VerticalScroll)
            assert body.max_scroll_y > 0
            for key in ('command-confirmed', 'command-apply', 'command-cancel'):
                widget = dialog.query_one('#' + key)
                assert widget.region.bottom <= 24 and widget.region.y >= 0, (key, widget.region)
            apply = dialog.query_one('#command-apply', Button)
            cancel = dialog.query_one('#command-cancel', Button)
            assert apply.region.y == cancel.region.y
            assert apply.region.right <= cancel.region.x
            footer = dialog.query_one('#command-buttons')
            assert abs((apply.region.x + cancel.region.right) / 2 - footer.region.center[0]) <= 1
            assert await pilot.click('#command-cancel')
            await until(pilot, lambda: not isinstance(app.screen, CommandDialog))
            # Exercise real multi-target backend writes through the same dialog.
            ThreadAction.collect(context, definition)
            await until(pilot, lambda: isinstance(app.screen, CommandDialog) and app.screen.is_mounted)
            dialog = app.screen
            await until(pilot, lambda: not dialog.query_one('#command-apply', Button).disabled)
            assert await pilot.click('#command-confirmed')
            assert await pilot.click('#command-apply')
            await until(pilot, lambda: not isinstance(app.screen, CommandDialog)
                        and not app.thread_actions.requests
                        and not any(name in sidebar.projection.channels for name in targets))
            snapshot = await app.preparation.run_thread(comms.registry.snapshot)
            assert all(not snapshot.require(f'member-{index}').tags for index in range(30))
            assert not snapshot.require('idle-member').tags
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print('PASS: 30-tag warning scrolls; buttons visible at 85x24; real batch removal; idle/stopped counts survive filters')


if __name__ == '__main__':
    asyncio.run(main())
