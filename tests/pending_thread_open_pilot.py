"""One actual logical tab through delayed SDK load, painted history and reply."""
import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
import shlex
import sys
from tempfile import TemporaryDirectory
from threading import Event, enumerate as threads
from unittest.mock import patch
from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from runtime_fixture import ToadApp, private_native_wire, wait_channel_roster
from toad.widgets.comms_sidebar import ChannelGroup
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad import messages
from toad.navigation_preparation import ThreadNavigationRequest
from toad.widgets.conversation import ThreadLoading
from toad.directory_watcher import DirectoryWatcher


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")

    def __init__(self, **kwargs):
        self.painted_tabs = []
        super().__init__(**kwargs)

    async def _close_all(self):
        print("BEFORE_DOMAIN_CLOSE", [(identity, str(view.presentation.sources.directory_watcher))
              for identity, view in self.workspace_sessions.views.items()
              if hasattr(view, "presentation")], flush=True)
        await super()._close_all()
        print("AFTER_DOMAIN_CLOSE", [(str(thread), str(thread._widget))
              for thread in threads() if isinstance(thread, DirectoryWatcher)], flush=True)

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if renderable is not None and not self._batch_count:
            self.painted_tabs.append(tuple((tab.mode_name, tab.title) for tab in self.open_tabs))


async def until(pilot, predicate):
    async with asyncio.timeout(12):
        while not predicate():
            await pilot.pause(.02)


def paint(app):
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


async def main():
    with TemporaryDirectory(prefix="single-tab-sdk-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), NAVIGATION_PEER_ROOT=str(root),
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"))
        comms = private_native_wire(root / "wire")
        for name in ("owner", "fresh-peer"):
            comms.registry.declare(Thread(name, frozenset({"journey"}), str(root),
                process_identity=ProcessIdentity.capture(os.getpid())))
        comms.channels.create_tag("journey")
        comms.messaging.send_initial_cohort("owner", "#journey", "SAVED_CHANNEL_JOURNEY")
        peer = Path(__file__).with_name("acp_navigation_server.py")
        data = {"name": "SDK first-open", "identity": "sdk-first-open", "short_name": "SDK",
                "protocol": "acp", "run_command": {"*": shlex.join([sys.executable, str(peer)])}}
        print("SDK_APP_CONSTRUCT", flush=True)
        app = InstalledApp(project_dir=str(root), agent_data=data, agent_session_id="owner")
        print("SDK_RUN_TEST", flush=True)
        async with app.run_test(size=(139, 25)) as pilot:
            print("SDK_APP_MOUNTED", flush=True)
            async with asyncio.timeout(8):
                try:
                    await app.selected_session.wait_content_ready()
                finally:
                    print("SOURCE_STARTUP", app._exception, [(str(w), str(w.error)) for w in app.workers if w.error], flush=True)
            source = app.selected_session
            await until(pilot, lambda: source.conversation.agent_ready)
            owner = app.selected_mode
            source.conversation.prompt.text = "RETAINED_DRAFT"
            editor = source.conversation.prompt.prompt_text_area
            document, undo = editor.document, editor.history
            app.screen.query_one(ChannelsSidebar).reveal()
            roster = await wait_channel_roster(app, pilot, "#journey")
            await pilot.pause()
            group = next(g for g in roster.query(ChannelGroup) if g.row.target_name == "#journey")
            assert await pilot.click(group.row)
            await until(pilot, lambda: app.selected_mode != owner)
            channel = app.selected_mode
            await app.selected_session.wait_content_ready()
            await until(pilot, lambda: "SAVED_CHANNEL_JOURNEY" in paint(app))
            await app.select_session(owner)
            await until(pilot, lambda: source.conversation.agent_ready)
            assert source.conversation.prompt.text == "RETAINED_DRAFT"
            assert editor.document is document and editor.history is undo
            await app.select_session(channel)
            await until(pilot, lambda: "SAVED_CHANNEL_JOURNEY" in paint(app))
            roster = await wait_channel_roster(app, pilot, "#journey")
            group = next(g for g in roster.query(ChannelGroup) if g.row.target_name == "#journey")
            group.toggle_members()
            await until(pilot, lambda: "fresh-peer" in group._members)
            initial_modes = tuple(app.tab_order.names)
            entered, release = Event(), Event()
            original = ThreadNavigationRequest.read

            def gated(request):
                entered.set()
                assert release.wait(10)
                return original(request)

            with patch.object(ThreadNavigationRequest, "read", gated):
                assert await pilot.click(group._members["fresh-peer"])
                opening = asyncio.create_task(app.thread_navigation.open(
                    owner_mode=owner, project_path=root, target="fresh-peer"))
                try:
                    assert await asyncio.to_thread(entered.wait, 3)
                    duplicate = asyncio.create_task(app.thread_navigation.open(
                        owner_mode=owner, project_path=root, target="fresh-peer"))
                    await pilot.pause()
                    assert tuple(app.tab_order.names) == initial_modes
                    assert len(app.thread_navigation.pending) == 1 and not duplicate.done()
                    release.set()
                    await until(pilot, lambda: (root / "load-entered-fresh-peer").exists())
                    mode = app.selected_mode
                    assert mode != owner
                    view = app.selected_session
                    agent = view.conversation.agent
                    print("BEFORE_CHILD_READY", mode, view.id, view._comms_thread, agent.session_id, view.conversation.agent_ready, [(type(n).__name__, str(n.region)) for n in view.conversation.contents.children], flush=True)
                    await until(pilot, lambda: bool(view.query(ThreadLoading)))
                    await until(pilot, lambda: "Loading new thread" in paint(app))
                    assert tuple(app.tab_order.names) == (*initial_modes, mode)
                    details = app.session_tracker.get_session(mode)
                    print("INITIAL_TAB_STATUS", details.title, details.state, details.summary, flush=True)
                    assert details.title == "fresh-peer" and details.state == "notready"
                    (root / "allow-fresh-peer").touch()
                    assert await opening == mode and await duplicate == mode
                    await until(pilot, lambda: view.conversation.agent_ready)
                    await until(pilot, lambda: "SAVED_FIRST_OPEN_fresh-peer" in paint(app))
                    assert app.selected_session is view and view.conversation.agent is agent
                    assert app.session_tracker.get_session(mode) is details
                    await until(pilot, lambda: not view.query(ThreadLoading))
                    await view.conversation.submit_input(messages.UserInputSubmitted("FIRST_MESSAGE"))
                    await until(pilot, lambda: "ONE_ANSWER_FIRST_MESSAGE" in paint(app))
                    rows = [json.loads(line) for line in (root / "sdk-inputs.jsonl").read_text().splitlines()]
                    assert rows == [{"session": "fresh-peer", "text": "FIRST_MESSAGE"}]
                    assert tuple(app.tab_order.names) == (*initial_modes, mode)
                    assert all(len(frame) <= 3 and all(not name.startswith("pending-") for name, _ in frame)
                               for frame in app.painted_tabs)
                    assert app._exception is None
                    Path("evidence/first-fork/single-tab-sdk.svg").write_text(app.export_screenshot())
                    print("PHYSICAL_SDK_CONTINUOUS_SAVED_CHANNEL_PARTICIPANT_RETURN_ONE_TAB_REPLY_ONCE", mode, flush=True)
                finally:
                    release.set()
        assert not any(isinstance(thread, DirectoryWatcher) for thread in threads())
        print("CONTINUOUS_JOURNEY_AND_RETIRED_PROCESS_PASS", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
