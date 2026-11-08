"""Toad observes a Core across the connector, through the owner's HTTPS UI profile.

The connector serves the workspace's own bus over TLS on loopback; Toad opens it
with a RemoteCoreConnection exactly as `--comms-profile PATH` would, so the
sidebar it shows was observed through the connector, not read from the local
service.
"""

import asyncio
import os
import socket
import ssl
import threading
from contextlib import contextmanager
from pathlib import Path

from aiohttp import web
from yarl import URL

from agent_comms.channel_targets import CommandTarget
from agent_comms.connector import Connector
from agent_comms.connector_profile import HttpsMcpEndpoint
from agent_comms.connector_store import ConnectorStore, UiAccess, UiGrantAccess, UiReadAccess
from agent_comms.read_basis import NamedViewer
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.threads import ExternalThread

from toad.comms_root import RemoteCoreConnection, RemoteObserving
from toad.render_processes import RenderProcessPool
from toad.widgets.transcript_lines import TranscriptLinesBatchRenderTask
from toad.widgets.comms_sidebar import CommsSidebar

TLS = Path(__file__).parents[1] / "support" / "tls"
# The first remote answer waits for the connector to spawn its observation service (about
# 9 s on this host), on top of Toad's own startup.
REMOTE_FIRST_ANSWER = 45


class ConnectorThread:
    """The connector on its own thread and event loop, as it runs in its own process in
    production: Toad's loop and executor never serve the connector's relay."""

    def __init__(self, connector: Connector, listener: socket.socket, served: ssl.SSLContext) -> None:
        self.loop = asyncio.new_event_loop()
        self.started = threading.Event()
        self.thread = threading.Thread(
            target=self.loop.run_until_complete, args=(self.serve(connector, listener, served),),
            name="test-connector", daemon=True)
        self.thread.start()
        if not self.started.wait(30):
            raise TimeoutError("The test connector did not start")

    async def serve(self, connector: Connector, listener: socket.socket, served: ssl.SSLContext) -> None:
        self.stopped = asyncio.Event()
        runner = web.AppRunner(connector.application())
        await runner.setup()
        await web.SockSite(runner, listener, ssl_context=served).start()
        self.started.set()
        try:
            await self.stopped.wait()
        finally:
            await runner.cleanup()

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.stopped.set)
        self.thread.join(30)
        self.loop.close()


@contextmanager
def remote_core(workspace, tmp_path, monkeypatch, access: type[UiGrantAccess] = UiReadAccess):
    """The workspace's Core behind a loopback TLS connector, and a profile granted for it."""
    monkeypatch.setenv("SSL_CERT_FILE", str(TLS / "loopback-cert.pem"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    comms = workspace.comms
    store = ConnectorStore.at(tmp_path / "auth")
    granted = store.update(
        lambda grants: grants.ui_issued(comms.registry.store.privacy().namespace, 600, access))
    served = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    served.load_cert_chain(TLS / "loopback-cert.pem", TLS / "loopback-key.pem")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    connector = ConnectorThread(Connector(store, f"https://127.0.0.1:{port}", comms.root), listener, served)
    try:
        yield RemoteCoreConnection(HttpsMcpEndpoint(URL(f"https://127.0.0.1:{port}/mcp")), granted)
    finally:
        connector.stop()


async def test_a_remote_core_shows_its_sidebar_through_the_connector(workspace, tmp_path, monkeypatch):
    workspace.thread("remote-peer", "team")
    with remote_core(workspace, tmp_path, monkeypatch) as connection:
        async with workspace.app(session=False, connect=lambda _: connection) as ui:
            app, _ = ui.textual
            observed = app.coordination_access.observation
            assert isinstance(observed, RemoteObserving)
            assert observed.root == workspace.comms.root.resolve()
            sidebar = app.workspace_chrome.channels
            if sidebar.collapsed:
                sidebar.toggle()
            tree = sidebar.query_one(CommsSidebar)
            await ui.until(lambda: "#team" in tree.groups, seconds=REMOTE_FIRST_ANSWER,
                           why="the remote Core's channel group")


async def test_a_remote_core_opens_a_thread_and_sends_to_it_through_the_connector(
        workspace, tmp_path, monkeypatch):
    # A thread run elsewhere: its mailbox takes the owner's input, as from the sidebar locally.
    workspace.comms.registry.declare(ExternalThread(
        "remote-peer", frozenset({"team"}), Checkout(workspace.project)))

    def sent():
        return tuple(message for message in workspace.comms.views.history_page(
            CommandTarget.named("remote-peer"), viewer=NamedViewer(workspace.viewer),
        ).messages if message.body == "hello through the connector")

    with remote_core(workspace, tmp_path, monkeypatch, UiAccess) as connection:
        async with workspace.app(session=False, connect=lambda _: connection) as ui:
            app, _ = ui.textual
            sidebar = app.workspace_chrome.channels
            if sidebar.collapsed:
                sidebar.toggle()
            tree = sidebar.query_one(CommsSidebar)
            await ui.until(lambda: "#team" in tree.groups, seconds=REMOTE_FIRST_ANSWER,
                           why="the remote Core's channel group")
            group = tree.groups["#team"]
            if not group.expanded:
                group.toggle_members()
            await ui.until(lambda: "remote-peer" in group.rows, why="the remote thread's row")
            group.rows["remote-peer"].open_selected()
            await ui.until(
                lambda: app.selected_session is not None
                and app.selected_session.thread_identity.thread_name() == "remote-peer",
                why="the remote thread's tab")
            await app.selected_session.wait_content_ready()
            await ui.write_draft("hello through the connector")
            await ui.press("enter")
            await ui.until(sent, why="the message on the wire")
            assert sent()[0].sender == workspace.viewer


async def test_a_remote_core_lists_a_target_menu_and_keeps_its_root_spelling(
        workspace, tmp_path, monkeypatch):
    """The menu captures its source through the connector's observation, not a local route
    selection; and Core's served root is compared as Core spells it, never resolved here."""
    from toad.comms_root import CurrentObservation
    from toad.target_commands import TargetContext

    workspace.thread("remote-peer", "team")
    with remote_core(workspace, tmp_path, monkeypatch) as connection:
        async with workspace.app(session=False, connect=lambda _: connection) as ui:
            app, _ = ui.textual
            sidebar = app.workspace_chrome.channels
            if sidebar.collapsed:
                sidebar.toggle()
            tree = sidebar.query_one(CommsSidebar)
            await ui.until(lambda: "#team" in tree.groups, seconds=REMOTE_FIRST_ANSWER,
                           why="the remote Core's channel group")
            observed = app.coordination_access.observation
            captured = app.coordination_access.selected(observed.root)
            assert captured == CurrentObservation(observed)
            context = TargetContext(app, observed, CommandTarget.named("remote-peer"),
                                    workspace.viewer, Checkout(workspace.project))
            actions = await asyncio.to_thread(context.available_actions)
            assert actions
            # A completed thread action reconnects through the same capture.
            await app.session_navigation.reconnect(captured, ("remote-peer",))

            spelled_elsewhere = tmp_path / "served-root-alias"
            spelled_elsewhere.symlink_to(observed.root)
            assert observed.observes(observed.root)
            assert not observed.observes(spelled_elsewhere)


async def test_a_remote_target_menu_and_reconnect_read_registry_slices_not_the_whole_registry(
        workspace, tmp_path, monkeypatch):
    """Over the connector the whole registry is megabytes; a menu render and a reconnect name
    their targets, so they read those rows. A full read here once kept 3-7 whole-registry
    transfers in flight and froze a remote Toad."""
    from toad.comms_root import CurrentObservation
    from toad.target_commands import TargetContext

    workspace.thread("remote-peer", "team")
    with remote_core(workspace, tmp_path, monkeypatch) as connection:
        async with workspace.app(session=False, connect=lambda _: connection) as ui:
            app, _ = ui.textual
            sidebar = app.workspace_chrome.channels
            if sidebar.collapsed:
                sidebar.toggle()
            tree = sidebar.query_one(CommsSidebar)
            await ui.until(lambda: "#team" in tree.groups, seconds=REMOTE_FIRST_ANSWER,
                           why="the remote Core's channel group")
            observed = app.coordination_access.observation
            captured = app.coordination_access.selected(observed.root)
            assert captured == CurrentObservation(observed)
            whole = []
            original = RemoteObserving.registry

            def counted(self):
                whole.append(self)
                return original(self)

            monkeypatch.setattr(RemoteObserving, "registry", counted)
            context = TargetContext(app, observed, CommandTarget.named("remote-peer"),
                                    workspace.viewer, Checkout(workspace.project))
            assert await asyncio.to_thread(context.available_actions)
            await app.session_navigation.reconnect(captured, ("remote-peer",))
            assert whole == []


async def test_opening_a_remote_channel_reads_its_declaration_not_the_whole_registry(
        workspace, tmp_path, monkeypatch):
    """A channel opening once resolved every member through the whole registry, about 6 s over
    the Funnel, and kept only the channel's name and the viewer's."""
    from toad.conversation_kind import ChannelConversation

    workspace.thread("remote-peer", "team")
    with remote_core(workspace, tmp_path, monkeypatch) as connection:
        async with workspace.app(session=False, connect=lambda _: connection) as ui:
            app, _ = ui.textual
            sidebar = app.workspace_chrome.channels
            if sidebar.collapsed:
                sidebar.toggle()
            tree = sidebar.query_one(CommsSidebar)
            await ui.until(lambda: "#team" in tree.groups, seconds=REMOTE_FIRST_ANSWER,
                           why="the remote Core's channel group")
            observed = app.coordination_access.observation
            whole = []
            original = RemoteObserving.registry

            def counted(self):
                whole.append(self)
                return original(self)

            monkeypatch.setattr(RemoteObserving, "registry", counted)
            resolved = await asyncio.to_thread(
                ChannelConversation.resolve, observed, workspace.viewer, "#team")
            assert resolved.conversation.target.name == "#team"
            assert resolved.viewer == workspace.viewer
            assert whole == []


def execute_with_process_identity(function, arguments):
    """Diagnostic transport witness: run the original job in its actual worker."""
    return os.getpid(), function(*arguments)


async def test_remote_conversation_prepares_transcript_lines_in_a_render_process(
        workspace, tmp_path, monkeypatch):
    workspace.thread("remote-peer", "team")
    workspace.thread("source")
    workspace.comms.messaging.send("source", "remote-peer", "REMOTE_RENDER_WORKER_PROOF **fresh content**")
    completed = []
    run = RenderProcessPool.run

    async def witnessed(pool, function, *arguments):
        pid, result = await run(pool, execute_with_process_identity, function, arguments)
        completed.append((pid, type(function.__self__)))
        return result

    monkeypatch.setattr(RenderProcessPool, "run", witnessed)
    with remote_core(workspace, tmp_path, monkeypatch, UiAccess) as connection:
        async with workspace.app(session=False, connect=lambda _: connection) as ui:
            app, _ = ui.textual
            sidebar = app.workspace_chrome.channels
            if sidebar.collapsed:
                sidebar.toggle()
            tree = sidebar.query_one(CommsSidebar)
            await ui.until(lambda: "#team" in tree.groups, seconds=REMOTE_FIRST_ANSWER,
                           why="the remote sidebar")
            group = tree.groups["#team"]
            if not group.expanded:
                group.toggle_members()
            await ui.until(lambda: "remote-peer" in group.rows, why="the remote thread row")
            group.rows["remote-peer"].open_selected()
            await ui.until(lambda: any(kind is TranscriptLinesBatchRenderTask for _, kind in completed),
                           seconds=REMOTE_FIRST_ANSWER, why="fresh remote lines to finish in a render process")
            line_jobs = [(pid, kind) for pid, kind in completed if kind is TranscriptLinesBatchRenderTask]
            assert line_jobs
            assert all(pid != os.getpid() for pid, _ in line_jobs)
            print(f"Remote transcript line jobs: {len(line_jobs)}; UI PID {os.getpid()}; worker PIDs {sorted({pid for pid, _ in line_jobs})}")
