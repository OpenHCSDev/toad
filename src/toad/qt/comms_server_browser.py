"""Live ZMQ comms server browser over ``pyqt_reactive.ZMQServerBrowserWidgetABC``.

Mirrors OpenHCS's ``ZMQServerManagerWidget``: connects ``CommsZMQConfig`` and
``ZMQServerScanService`` to the shared ``ZMQServerBrowserWidgetABC`` tree UI so
users see live comms server state (connected/disconnected, PID, bus root, attached
CLI workers) with Refresh, Quit, and Force Kill actions.
"""

from __future__ import annotations

from pathlib import Path

from agent_comms.transport.zmq_comms_server import (
    DEFAULT_COMMS_ZMQ_PORT,
    CommsZMQConfig,
)
from formbridge.services.zmq_server_info import BaseServerInfo, ExecutionServerInfo
from formbridge.services.zmq_server_scan_service import ZMQServerScanService
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared import ZMQServerBrowserWidgetABC
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from zmqruntime import TransportMode

from toad.qt.metrics import UiGap
from toad.qt.presented_window import PresentedWindow


class CommsServerBrowserWidget(ZMQServerBrowserWidgetABC):
    """Live browser for ``CommsZMQServer`` endpoints and attached CLI sessions."""

    def __init__(
        self,
        config: CommsZMQConfig,
        *,
        ports_to_scan: list[int] | None = None,
        host: str = "127.0.0.1",
        transport_mode: TransportMode = TransportMode.IPC,
        timeout_ms: int = 1000,
        color_scheme: ColorScheme | None = None,
        title: str = "Comms ZMQ Servers",
        parent: QWidget | None = None,
    ) -> None:
        self._config = config
        self._ports_to_scan = list(ports_to_scan) if ports_to_scan is not None else [
            config.default_port
        ]
        scan_service = ZMQServerScanService(
            config=config,
            host=host,
            transport_mode=transport_mode,
            timeout_ms=timeout_ms,
        )
        super().__init__(
            ports_to_scan=self._ports_to_scan,
            title=title,
            color_scheme=color_scheme or ColorScheme(),
            scan_service=scan_service,
            parent=parent,
        )
        self.render_endpoint_snapshot(self._endpoint_authority.snapshot)

    def scan_once(self, *, fresh: bool = True) -> None:
        """Run one synchronous endpoint scan and render the resulting snapshot immediately."""
        authority = self._endpoint_authority
        snapshot = authority.scan_service.scan_ports(
            authority.ports,
            previous_snapshot=None if fresh else authority.snapshot,
        )
        self._commit_endpoint_snapshot(snapshot)

    def populate_tree(self, parsed_servers: list[BaseServerInfo]) -> None:
        if not parsed_servers:
            for port in self._ports_to_scan:
                item = QTreeWidgetItem(
                    [
                        f"Port {port} - CommsZMQServer",
                        "❌\ufe0e Disconnected",
                        f"Bus root: {self._config.bus_root}",
                    ]
                )
                self.server_tree.addTopLevelItem(item)
            return

        for server_info in parsed_servers:
            status_text = "✅\ufe0e Connected" if server_info.ready else "🚀 Starting"
            info_parts: list[str] = []
            identity = server_info.response.process_identity
            if identity is not None:
                info_parts.append(f"PID {identity.pid}")
            workers = (
                server_info.workers
                if isinstance(server_info, ExecutionServerInfo)
                else ()
            )
            cli_word = "CLI" if len(workers) == 1 else "CLIs"
            info_parts.append(f"{len(workers)} {cli_word}")
            info_parts.append(f"Bus: {self._config.bus_root.name}")
            item = QTreeWidgetItem(
                [
                    f"Port {server_info.port} - {server_info.server_name}",
                    status_text,
                    " · ".join(info_parts),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, server_info)
            self.server_tree.addTopLevelItem(item)

            for worker in workers:
                child = QTreeWidgetItem(
                    [
                        f"CLI · {worker.status}",
                        "Connected",
                        f"PID {worker.pid}",
                    ]
                )
                item.addChild(child)
            item.setExpanded(True)

    def periodic_domain_cleanup(self) -> None:
        return None

    def on_browser_shown(self) -> None:
        return None

    def on_browser_hidden(self) -> None:
        return None

    def on_browser_cleanup(self) -> None:
        return None


class QtCommsServerWindow(PresentedWindow, QDialog):
    """Modal window hosting ``CommsServerBrowserWidget`` inside ``QtToadApp``."""

    def __init__(
        self,
        bus_root: Path,
        *,
        port: int = DEFAULT_COMMS_ZMQ_PORT,
        transport_mode: TransportMode = TransportMode.IPC,
        color_scheme: ColorScheme | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__()
        if parent is not None:
            self.setParent(parent)
        self.setWindowTitle("Comms ZMQ Servers")
        self.resize(780, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.dialog, UiGap.dialog, UiGap.dialog, UiGap.dialog)
        layout.setSpacing(UiGap.normal)

        config = CommsZMQConfig.for_root(bus_root, port=port)
        self.browser = CommsServerBrowserWidget(
            config=config,
            transport_mode=transport_mode,
            color_scheme=color_scheme,
            parent=self,
        )
        layout.addWidget(self.browser, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def closeEvent(self, event) -> None:
        self.browser.on_browser_cleanup()
        super().closeEvent(event)


__all__ = [
    "CommsServerBrowserWidget",
    "QtCommsServerWindow",
]
