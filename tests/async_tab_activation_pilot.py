"""Native activation paints before blocked hydration; typed routes own dispatch."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.comms import wire
from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.agent import AgentReady
from toad.conversation_kind import ConversationKind, ChannelConversation, DmConversation, IrcConversation
from toad.constants import ALL_COMMS_TARGET
from toad.navigation_target import NavigationContext, ThreadTarget, ChannelTarget, DirectTarget, FeedTarget
from toad.screens.pending_thread import PendingTabShells
from toad.widgets.comms_sidebar import CommsSidebar


class FrameApp(ToadApp):
    def __init__(self, **kwargs):
        self.presented = []
        super().__init__(**kwargs)

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if renderable is not None and not self._batch_count and screen is self.screen:
            self.presented.append(screen)


async def until(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(.01)


async def main():
    with TemporaryDirectory(prefix="toad-async-tabs-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        comms.threads.register(Thread("peer", frozenset(), str(root), process_identity=ProcessIdentity.capture(os.getpid())))

        async def start(agent, target):
            agent._message_target = target
            agent._task = asyncio.create_task(asyncio.sleep(0))
            target.post_message(AgentReady())

        app = FrameApp(project_dir=str(root))
        with patch.object(Agent, "start", start):
            async with app.run_test(size=(110, 36)) as pilot:
                await pilot.pause()
                owner, original = app.current_mode, app.screen
                await until(lambda: len(app.pending_tab_shells._available) == app.PREPARED_TAB_SHELLS)
                prepared_shell = app.pending_tab_shells._available[0]
                assert not prepared_shell._first_frame_presented and not prepared_shell.is_current
                assert not prepared_shell.query(CommsSidebar), "Lookahead duplicated the shared roster"
                for invalid in (-1, True, 1.5):
                    try:
                        PendingTabShells(app, invalid)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError("Invalid shell budget accepted")
                cold_shells = PendingTabShells(app, 0)
                cold_shells.prepare()
                assert not cold_shells._preparing
                cold_shell = await cold_shells.acquire(NavigationContext(app, owner, root, "actor"))
                assert cold_shell.is_mounted and not cold_shell._first_frame_presented
                assert not cold_shell.query(CommsSidebar)
                await app.remove_mode(cold_shell.id)
                cold_shells.close()
                original._agent = {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
                                   "run_command": {"*": "/bin/false"}, "protocol": "acp"}
                destination = await app.open_thread_session(owner_mode=owner, project_path=root, target="peer")
                await pilot.pause()
                await app.switch_mode(owner)
                await pilot.pause()
                view = app.get_screen_stack(destination)[0]
                sidebar = app.shared_channels.bar.roster
                entered, release = asyncio.Event(), asyncio.Event()
                present = sidebar.present_cached_sessions

                async def blocked():
                    entered.set()
                    await release.wait()
                    await present()

                app.presented.clear()
                with patch.object(sidebar, "present_cached_sessions", blocked):
                    try:
                        await asyncio.wait_for(app.switch_mode(destination), 3)
                        await asyncio.wait_for(entered.wait(), 3)
                        assert view in app.presented, "Sidebar rebuilt before activation was painted"
                        assert not sidebar.navigation_ready.is_set()
                        await pilot.pause()
                        assert app._batch_count == 0, "Blocked hydration owns a global paint mask"
                        view.conversation.prompt.focus()
                        await pilot.press("s", "a", "f", "e")
                        assert view.conversation.prompt.text.endswith("safe")
                        await asyncio.wait_for(app.switch_mode(owner), 3)
                        original.conversation.prompt.focus()
                        await pilot.press("o", "k")
                        assert original.conversation.prompt.text.endswith("ok")
                    finally:
                        release.set()
                    await pilot.pause()
                await app.switch_mode(destination)
                await until(sidebar.navigation_ready.is_set)
                assert view.conversation.prompt.text.endswith("safe")

                # External strings enter one registry boundary. Polymorphic
                # targets call the appropriate executor with unchanged context.
                context = NavigationContext(app, owner, root, "actor")
                with (
                    patch.object(app, "open_thread_session", new_callable=AsyncMock) as thread,
                    patch.object(app, "_open_comms_history", new_callable=AsyncMock) as history,
                ):
                    await ThreadTarget("peer").open(context)
                    thread.assert_awaited_once_with(owner_mode=owner, project_path=root, target="peer")
                    for target, expected_kind, expected_name in (
                        (ChannelTarget("#room"), ChannelConversation, "#room"),
                        (FeedTarget(), IrcConversation, ALL_COMMS_TARGET),
                        (DirectTarget("peer"), DmConversation, "peer"),
                    ):
                        await target.open(context)
                        history.assert_awaited_with(owner_mode=owner, project_path=root, me="actor",
                                                    target=expected_name, kind=expected_kind)

                entered, release = asyncio.Event(), asyncio.Event()
                update_group = sidebar._update_channel_group

                async def blocked_group(*args):
                    entered.set()
                    await release.wait()
                    await update_group(*args)

                snapshot = sidebar._last_snapshot
                sidebar._last_snapshot = None
                with patch.object(sidebar, "_update_channel_group", blocked_group):
                    publication = asyncio.create_task(sidebar._present_snapshot(snapshot))
                    try:
                        await asyncio.wait_for(entered.wait(), 3)
                        await asyncio.wait_for(app.close_session_mode(destination), 4)
                    finally:
                        release.set()
                    await asyncio.wait_for(publication, 3)
                assert sidebar.is_attached and sidebar._ordered_rows(), "Closing a tab retired shared navigation"
                assert all(row.mode_name != destination for row in sidebar.session_rows), (
                    "A stale publication restored the closed tab's route")
                assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("async activation: frame before blocked rows, input/switch preserved, typed target dispatch")


if __name__ == "__main__":
    asyncio.run(main())
