"""Isolated-display Qt tests for CommsServerBrowserWidget over ZMQServerBrowserWidgetABC."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.installer.active_route import CommsRoute
from agent_comms.transport.zmq_comms_server import (
    CommsZMQClient,
    CommsZMQConfig,
    CommsZMQServer,
)
from PySide6.QtWidgets import QApplication
from zmqruntime import TransportMode

from toad.client.application_actions import ApplicationAction, CommsServersAction
from toad.qt.comms_server_browser import CommsServerBrowserWidget, QtCommsServerWindow


def _qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return port if port < 60000 else 17791


def _start_server(server: CommsZMQServer) -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    started = threading.Event()

    def _run() -> None:
        server.start()
        started.set()
        try:
            while server.is_running() and not stop.is_set():
                server.process_messages()
                time.sleep(0.005)
        finally:
            server.stop()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    assert started.wait(timeout=5.0)
    return thread, stop


def test_comms_server_browser_live_state_and_attached_clis(tmp_path: Path) -> None:
    _qt_app()
    root = tmp_path / "comms"
    comms = Comms(CommsRoute(root))
    port = _free_port()
    config = CommsZMQConfig.for_root(root, port=port)

    window = QtCommsServerWindow(root, port=port, transport_mode=TransportMode.IPC)
    browser = window.browser
    assert isinstance(browser, CommsServerBrowserWidget)

    # 1. Before server starts: browser reports Disconnected clearly.
    browser.scan_once()
    assert browser.server_tree.topLevelItemCount() == 1
    disconnected_row = browser.server_tree.topLevelItem(0)
    assert disconnected_row is not None
    assert "Disconnected" in disconnected_row.text(1)

    server = CommsZMQServer(
        comms,
        port=port,
        host="127.0.0.1",
        transport_mode=TransportMode.IPC,
        config=config,
    )
    thread, stop = _start_server(server)
    client = CommsZMQClient(
        root,
        port=port,
        host="127.0.0.1",
        transport_mode=TransportMode.IPC,
        config=config,
    )
    try:
        assert client.connect_existing(timeout=3.0) is True
        client.attach_cli("claude-main", client_kind="claude", pid=1111)
        client.attach_cli("codex-worker", client_kind="codex", pid=2222)

        # 2. Live scan shows Connected server and both attached CLI children.
        browser.scan_once()
        assert browser.server_tree.topLevelItemCount() == 1
        connected_row = browser.server_tree.topLevelItem(0)
        assert connected_row is not None
        assert "Connected" in connected_row.text(1)
        assert "2 CLIs" in connected_row.text(2)
        assert connected_row.childCount() == 2
        child_labels = {connected_row.child(i).text(0) for i in range(connected_row.childCount())}
        assert child_labels == {"CLI · claude:claude-main", "CLI · codex:codex-worker"}

        # 3. Detaching one CLI updates live server browser state.
        client.detach_cli("codex-worker", pid=2222)
        browser.scan_once()
        updated_row = browser.server_tree.topLevelItem(0)
        assert updated_row is not None
        assert "1 CLI" in updated_row.text(2)
        assert updated_row.childCount() == 1
        assert updated_row.child(0).text(0) == "CLI · claude:claude-main"

        # 4. Graceful shutdown returns browser to Disconnected.
        result = client.shutdown_server()
        assert result.succeeded is True
        thread.join(timeout=3.0)
        browser.scan_once()
        after_stop = browser.server_tree.topLevelItem(0)
        assert after_stop is not None
        assert "Disconnected" in after_stop.text(1)
    finally:
        client.disconnect()
        stop.set()
        thread.join(timeout=3.0)
        window.close()


def test_comms_servers_action_dispatches_to_open_comms_servers() -> None:
    assert CommsServersAction in ApplicationAction.members_with(ApplicationAction)
    called: list[str] = []

    class _FakeApp:
        async def open_comms_servers(self) -> None:
            called.append("opened")

    asyncio.run(CommsServersAction().apply(_FakeApp()))  # type: ignore[arg-type]
    assert called == ["opened"]
