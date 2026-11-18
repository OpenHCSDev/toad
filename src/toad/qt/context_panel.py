"""Qt rendering of the Context thread-sidebar panel.

Reads the same `InspectionState` / `HoldingInspection` state machine Textual's
`ContextExplorer` reads (`toad.core.context_inspection`), produces the same
`HoldingInspection.groups()` toolkit-neutral tuple, and shares the per-thread
`ContextTreeIntent` store (`toad.client.context_intent`) so inspection state
survives tab switches on Qt the same way it does on Textual.

Scope v1: live context read, grouped tree render, detail-on-select, Copy to
clipboard, search filter. Follow-ups: Correct, Export, Older/Newer pagination,
Read-full. All of those are UI affordances over the already-shared state
machine and intent store — no further decoding to lift.
"""
from __future__ import annotations

import asyncio
from typing import ClassVar

from PySide6.QtCore import Qt
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from PySide6.QtGui import QClipboard
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from toad.qt.session_panel import SessionPanel
from toad.client.context_intent import ContextInspectionReader, ContextTreeIntent
from toad.core.context_inspection import (
    ContextNode,
    DetachedInspection,
    HoldingInspection,
    InspectionState,
)
from toad.thread_identity import SessionIdentity
from toad.qt.metrics import UiGap


class QtContextExplorer(ContextInspectionReader, SessionPanel, QWidget, metaclass=PyQtWidgetMeta):
    spec_key: ClassVar[str] = "context"
    """Which `ThreadSidebarPanelSpec.key` this widget renders — mirrors the TUI
    `SessionPanel.spec_key` convention so both frontends share one identity per panel."""

    """Qt sibling of `widgets.context_explorer.ContextExplorer`.

    The state machine (`InspectionState`) and group decoding (`HoldingInspection.groups`)
    are shared with Textual; this class is the Qt renderer + its asyncio-based
    read coordinator. No re-typed intent management or group decoding — both
    live on the shared owners referenced above.
    """

    def __init__(
        self,
        intents: dict[SessionIdentity, ContextTreeIntent],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.start_inspection(intents)
        self._refresh_task: asyncio.Task | None = None

        column = QVBoxLayout(self)
        column.setContentsMargins(UiGap.frame, UiGap.normal, UiGap.frame, UiGap.normal)
        column.setSpacing(UiGap.normal)

        self._status = QLabel("Context · select a segment to inspect", self)
        self._status.setWordWrap(True)
        column.addWidget(self._status)

        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Search current context · Enter")
        self._search.returnPressed.connect(self._on_search)
        column.addWidget(self._search)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.itemSelectionChanged.connect(self._on_selection)
        self._tree.itemExpanded.connect(self._on_expanded)
        self._tree.itemCollapsed.connect(self._on_collapsed)
        column.addWidget(self._tree, 1)

        self._detail = QPlainTextEdit(self)
        self._detail.setReadOnly(True)
        self._detail.setPlainText("No context selected.")
        column.addWidget(self._detail, 1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self._copy = QPushButton("Copy detail", self)
        self._copy.clicked.connect(self._on_copy)
        row.addWidget(self._copy)
        row.addStretch(1)
        column.addLayout(row)

    # --- binding / present -------------------------------------------------

    def bind(self, view) -> None:
        """Follow the view the tab now shows; the welcome's `NoThreadIdentity` has no root,
        so the read says so and the tree stays empty."""
        self._view = view
        self.inspect_identity(self.thread_identity)
        intent = self.intent
        self._search.setText(intent.query)
        self.present()

    def present(self) -> None:
        asyncio.ensure_future(self._refresh())

    # --- shared state accessors (no Textual coupling) ----------------------

    @property
    def thread_identity(self) -> SessionIdentity:
        return self._view.thread_identity

    def _app(self):
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "coordination_access") and hasattr(parent, "preparation"):
                return parent
            parent = parent.parent()
        return None

    # --- read / render loop ------------------------------------------------

    async def _refresh(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.current_task()
        try:
            identity = self.thread_identity
            root = identity.root_path
            if root is None:
                self._status.setText("Context · no thread root")
                self._tree.clear()
                return
            app = self._app()
            if app is None:
                return
            access = app.coordination_access
            observed = await self.observed_source(access, app.preparation, root)
            if observed is None or identity != self.thread_identity:
                return
            previous = self.observe_revision(access.revision)
            acquired = await self.acquire_inspection(observed, access.revision, identity)
            if identity != self.thread_identity:
                return
            self.receive_inspection(acquired)
            self._status.setText(self.state.status)
            self.state.present(self._render_present)
        finally:
            self._refresh_task = None

    def show_source_unavailable(self, text: str) -> None:
        self._status.setText(text)
        self._tree.clear()

    def _render_present(self, holding: HoldingInspection) -> None:
        """Called by `InspectionState.present` once a HoldingInspection is ready. We
        kick off the groups build off the UI loop (same as Textual) and then paint."""
        asyncio.ensure_future(self._paint_groups(holding))

    async def _paint_groups(self, holding: HoldingInspection) -> None:
        app = self._app()
        if app is None:
            return
        # `HoldingInspection.groups()` is the toolkit-neutral decode. We call it off
        # the UI loop to match Textual's `Coordination.run_worker(captured.groups)`.
        groups = await app.preparation.run_thread(holding.groups)
        if holding.thread_identity != self.thread_identity:
            return
        self._apply_groups(groups)

    def _apply_groups(
        self, groups: tuple[tuple[str, tuple[ContextNode, ...], bool], ...]
    ) -> None:
        self._tree.clear()
        intent = self.intent
        query = intent.query.casefold()
        for label, models, expanded in groups:
            top = QTreeWidgetItem(self._tree, [label])
            top.setData(0, Qt.ItemDataRole.UserRole, None)
            for model in models:
                if query and query not in model.public_text().casefold():
                    continue
                self._add_node(top, model)
            top.setExpanded(expanded)

    def _add_node(self, parent_item: QTreeWidgetItem, model: ContextNode) -> None:
        row = QTreeWidgetItem(parent_item, [model.label])
        row.setData(0, Qt.ItemDataRole.UserRole, model)
        for child in model.children():
            self._add_node(row, child)
        if model.key in self.intent.expanded:
            row.setExpanded(True)

    # --- UI event handlers -------------------------------------------------

    def _on_selection(self) -> None:
        items = self._tree.selectedItems()
        if not items:
            return
        model = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(model, ContextNode):
            return
        self.intent.selected = model
        asyncio.ensure_future(self._show_detail(model))

    async def _show_detail(self, model: ContextNode) -> None:
        text = model.detail()
        # `ContextNode.read()` is what the Textual widget awaits for the full detail.
        # Not every node provides it; fall back to detail() above if absent.
        read = getattr(model, "read", None)
        if callable(read):
            try:
                text = await read()
            except Exception as error:
                # Keep the fallback detail() so the user still sees SOMETHING, but
                # surface the read failure so a recurring read bug leaves a trail
                # instead of a silently-truncated detail pane.
                import sys
                print(
                    f"context_panel: ContextNode.read() failed on {model!r}: {error!r}",
                    file=sys.stderr,
                )
        if self.intent.selected is model:
            self._detail.setPlainText(text)

    def _on_search(self) -> None:
        self.intent.query = self._search.text().strip()
        self.present()

    def _on_copy(self) -> None:
        clipboard: QClipboard = QApplication.clipboard()
        clipboard.setText(self._detail.toPlainText())

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        model = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(model, ContextNode):
            self.intent.expanded.add(model.key)

    def _on_collapsed(self, item: QTreeWidgetItem) -> None:
        model = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(model, ContextNode):
            self.intent.expanded.discard(model.key)
