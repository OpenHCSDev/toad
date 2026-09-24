"""Optional, read-only recovery status from the local viewer gateway."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual import events
from textual.binding import Binding
from textual.widgets import Static

from toad.widgets.side_bar import SideBarCollapsible


_UNAVAILABLE = "Recovery unavailable\n\n"


async def _read_gateway(path: Path, thread: str) -> dict[str, object]:
    """Optional client can be absent from older pinned agent-comms releases."""
    try:
        from agent_comms.recovery_gateway_client import read_gateway_projection
    except ImportError:
        return {"availability": "unavailable"}
    return await read_gateway_projection(path, thread)


class RecoveryView(Static):
    """A disposable presentation of a validated gateway DTO, never an owner."""

    DEFAULT_CSS = "RecoveryView { height: 3; text-wrap: nowrap; text-overflow: ellipsis; pointer: pointer; }"
    BINDINGS = [Binding("r", "refresh", "Refresh", show=False)]
    can_focus = True

    def __init__(self, thread: str, *, wire_root: str | Path | None = None) -> None:
        super().__init__(_UNAVAILABLE, markup=False)
        self.thread = thread
        self._wire_root = Path(wire_root).expanduser() if wire_root is not None else None
        self._enabled = False
        self._generation = 0
        self._read_task: asyncio.Task[None] | None = None
        self.tooltip = "Read-only recovery status · click or press R to refresh"

    def on_mount(self) -> None:
        self.app.settings_changed_signal.subscribe(self, self._settings_changed)
        self.app.mode_change_signal.subscribe(self, self._mode_changed)
        self._settings_changed(("ui.recovery-view", self.app.settings.get("ui.recovery-view", bool)))

    def _mode_changed(self, mode: str) -> None:
        if self._enabled and mode == self.screen.id:
            self._after_paint_read()

    def on_unmount(self) -> None:
        self._generation += 1
        if self._read_task is not None:
            self._read_task.cancel()

    def on_show(self) -> None:
        self._after_paint_read()

    def _settings_changed(self, update: tuple[str, object]) -> None:
        if update[0] != "ui.recovery-view":
            return
        enabled = update[1] is True
        self._enabled = enabled
        self.query_ancestor(SideBarCollapsible).display = enabled
        if enabled:
            self._after_paint_read()
        else:
            self._generation += 1
            if self._read_task is not None:
                self._read_task.cancel()
            self.update(_UNAVAILABLE, layout=False)

    def set_identity(self, thread: str, wire_root: str | Path | None) -> None:
        """Atomically retire a renamed or moved owner's old projection."""
        root = Path(wire_root).expanduser() if wire_root is not None else None
        if thread == self.thread and root == self._wire_root:
            return
        self.thread = thread
        self._wire_root = root
        self._generation += 1
        if self._read_task is not None:
            self._read_task.cancel()
        self.update(_UNAVAILABLE, layout=False)
        self._after_paint_read()

    def action_refresh(self) -> None:
        """Only a visible local UI action retries an unavailable gateway."""
        self._after_paint_read()

    def on_click(self, event: events.Click) -> None:
        if event.button == 1:
            event.stop()
            self.action_refresh()

    def _after_paint_read(self) -> None:
        if self._enabled and self.is_attached and self.screen is self.app.screen:
            self.call_after_refresh(self._fetch_if_visible)

    def _fetch_if_visible(self) -> None:
        if (not self._enabled or not self.is_attached or self.screen is not self.app.screen
                or self not in self.screen._compositor.visible_widgets):
            return
        if self._wire_root is None:
            self.update(_UNAVAILABLE, layout=False)
            return
        if self._read_task is not None and not self._read_task.done():
            return
        self._generation += 1
        self._read_task = asyncio.create_task(
            self._read(self._generation, self.thread, self._wire_root), name="read-recovery-view"
        )

    async def _read(self, generation: int, thread: str, root: Path) -> None:
        try:
            dto = await _read_gateway(root / ".recovery-viewer" / "gateway.sock", thread)
        except asyncio.CancelledError:
            raise
        except Exception:
            # This is a display-only optional view. Never fall back to private
            # stores, leak an error detail or start a missing gateway service.
            dto = {"availability": "unavailable"}
        if (generation != self._generation or not self.is_attached or not self._enabled
                or self.screen is not self.app.screen):
            return
        if dto.get("availability") != "available" or dto.get("owner") != thread:
            self.update(_UNAVAILABLE, layout=False)
            return
        current = dto.get("current") or {}
        recovery = dto.get("lastRecovery") or {}
        connection = dto.get("connectivity") or {}
        attempt = current.get("attempt") or {}
        self.update("\n".join((
            f"Execution: {current.get('status') or 'none'} · {attempt.get('phase') or 'none'}",
            f"Owner: {connection.get('owner') or 'unknown'} · ACP: {connection.get('acpClient') or 'unknown'}",
            f"Recovery: {recovery.get('kind') or 'none'}",
        )), layout=False)
