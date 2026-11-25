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

from agent_comms.coordination.errors import Refused
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
from toad.thread_sidebar_declarations import ContextSidebarPanel
from toad.qt.metrics import UiGap


class QtContextExplorer(ContextInspectionReader, SessionPanel, QWidget, metaclass=PyQtWidgetMeta):
    panel_type = ContextSidebarPanel

    """Qt sibling of `widgets.context_explorer.ContextExplorer`.

    The state machine (`InspectionState`) and group decoding (`HoldingInspection.groups`)
    are shared with Textual; this class is the Qt renderer + its asyncio-based
    read coordinator. No re-typed intent management or group decoding — both
    live on the shared owners referenced above.
    """

    def __init__(
        self,
        app,
        intents: dict[SessionIdentity, ContextTreeIntent],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._app = app
        self.start_inspection(intents)
        self._refresh_task: asyncio.Task | None = None
        self._native_task: asyncio.Task | None = None
        self._search_task: asyncio.Task | None = None

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
        self._tree.setIndentation(14)
        self._tree.itemSelectionChanged.connect(self._on_selection)
        self._tree.itemExpanded.connect(self._on_expanded)
        self._tree.itemCollapsed.connect(self._on_collapsed)
        column.addWidget(self._tree, 1)

        self._detail = QPlainTextEdit(self)
        self._detail.setReadOnly(True)
        self._detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._detail.setPlainText("No context selected.")
        column.addWidget(self._detail, 1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(UiGap.normal)
        self._older = QPushButton("Older", self)
        self._older.setEnabled(False)
        self._older.clicked.connect(self.older_requests)
        row.addWidget(self._older)
        self._newer = QPushButton("Newer", self)
        self._newer.setEnabled(False)
        self._newer.clicked.connect(self.newer_requests)
        row.addWidget(self._newer)
        self._refresh_btn = QPushButton("Refresh", self)
        self._refresh_btn.clicked.connect(self._on_refresh)
        row.addWidget(self._refresh_btn)
        self._copy = QPushButton("Copy", self)
        self._copy.clicked.connect(self._on_copy)
        row.addWidget(self._copy)
        row.addStretch(1)
        column.addLayout(row)

    # --- binding / present -------------------------------------------------

    def bind(self, view) -> None:
        """Follow the view the tab now shows; the welcome's `NoThreadIdentity` has no root,
        so the read says so and the tree stays empty."""
        previous_identity = self.thread_identity
        self._view = view
        identity = self.thread_identity
        identity_changed = identity != previous_identity
        if identity_changed:
            self._cancel_background()
            self.inspect_identity(identity)
            self._search.setText(self.intent.query)
            self._older.setEnabled(False)
            self._newer.setEnabled(False)
            self._tree.clear()
            self._detail.setPlainText("No context selected.")
        if self.isVisible():
            self.present(force=identity_changed)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.present(force=False)

    def _cancel_background(self) -> None:
        if self._native_task is not None and not self._native_task.done():
            self._native_task.cancel()
        self._native_task = None
        if self._search_task is not None and not self._search_task.done():
            self._search_task.cancel()
        self._search_task = None

    def present(self, *, force: bool = False) -> None:
        asyncio.ensure_future(self._refresh(force=force))

    # --- read / render loop ------------------------------------------------

    async def _refresh(self, *, force: bool = False) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.current_task()
        try:
            identity = self.thread_identity
            root = identity.root_path
            if root is None:
                self._status.setText("Context · no thread root")
                self._older.setEnabled(False)
                self._newer.setEnabled(False)
                self._tree.clear()
                return
            app = self._app
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
            self.state.present(lambda current: self._inspection_acquired(previous, current, force))
        finally:
            self._refresh_task = None

    def show_source_unavailable(self, text: str) -> None:
        self._status.setText(text)
        self._tree.clear()

    def set_page_controls(self, *, older: bool, newer: bool) -> None:
        self._older.setEnabled(older)
        self._newer.setEnabled(newer)

    def set_status_text(self, text: str) -> None:
        self._status.setText(text)

    def present_inspection(self, holding: HoldingInspection) -> None:
        self._render_present(holding)

    def native_running(self) -> bool:
        return self._native_task is not None and not self._native_task.done()

    def cancel_native_read(self) -> None:
        self._native_task.cancel()

    def start_native_read(self, captured: HoldingInspection) -> None:
        self._native_task = asyncio.ensure_future(self._run_native_read(captured))

    def _render_present(self, holding: HoldingInspection) -> None:
        """Called by `InspectionState.present` once a HoldingInspection is ready. We
        kick off search or the groups build off the UI loop (same as Textual) and then paint."""
        if self.intent.query:
            if self._search_task is not None and not self._search_task.done():
                self._search_task.cancel()
            selected = self.intent.selected
            description = (
                "Current public context" if selected is None else selected.search_description()
            )
            self._search_task = asyncio.ensure_future(
                self._run_search(holding, self.intent.query, selected, description)
            )
            return
        asyncio.ensure_future(self._paint_groups(holding))

    async def _run_search(
        self,
        holding: HoldingInspection,
        query: str,
        selected: ContextNode | None,
        description: str,
    ) -> None:
        self._status.setText("Searching public context…")
        matches = await holding.find(query, selected)
        if holding.thread_identity != self.thread_identity or self.intent.query != query:
            return
        self._tree.clear()
        top = QTreeWidgetItem(self._tree, [f"{description} · {query} ({len(matches)})"])
        top.setData(0, Qt.ItemDataRole.UserRole, None)
        for model in matches:
            self._add_node(top, model)
        top.setExpanded(True)
        self._status.setText(f"{len(matches)} matching sources · {description}")

    async def _paint_groups(self, holding: HoldingInspection) -> None:
        # `HoldingInspection.groups()` is the toolkit-neutral decode. We call it off
        # the UI loop to match Textual's `CoordinationWork.run_worker(captured.groups)`.
        groups = await self._app.preparation.run_thread(holding.groups)
        if holding.thread_identity != self.thread_identity or self.intent.query:
            return
        self._apply_groups(groups)

    def _apply_groups(
        self, groups: tuple[tuple[str, tuple[ContextNode, ...], bool], ...]
    ) -> None:
        self._tree.clear()
        for label, models, expanded in groups:
            top = QTreeWidgetItem(self._tree, [label])
            top.setData(0, Qt.ItemDataRole.UserRole, None)
            for model in models:
                self._add_node(top, model)
            top.setExpanded(expanded)

    def _add_node(self, parent_item: QTreeWidgetItem, model: ContextNode) -> None:
        row = QTreeWidgetItem(parent_item, [model.label])
        row.setData(0, Qt.ItemDataRole.UserRole, model)
        row.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        if model.key in self.intent.expanded:
            self._populate_children(row, model)
            row.setExpanded(True)

    def _populate_children(self, item: QTreeWidgetItem, model: ContextNode) -> None:
        if item.childCount() > 0:
            return
        if item.childIndicatorPolicy() == QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator:
            return
        children = model.children()
        if not children:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
            return
        for child in children:
            self._add_node(item, child)

    # --- UI event handlers -------------------------------------------------

    def _on_selection(self) -> None:
        items = self._tree.selectedItems()
        if not items:
            return
        model: ContextNode | None = items[0].data(0, Qt.ItemDataRole.UserRole)
        if model is None:
            return
        self.intent.selected = model
        asyncio.ensure_future(self._show_detail(model))

    async def _show_detail(self, model: ContextNode) -> None:
        text = await model.read()
        if self.intent.selected is model:
            self._detail.setPlainText(text)

    def _on_search(self) -> None:
        self.intent.query = self._search.text().strip()
        self.state.present(self._render_present)

    def _on_refresh(self) -> None:
        self.present(force=True)

    def cancel_page_work(self) -> None:
        self._cancel_background()

    def clear_page_display(self, placeholder: str) -> None:
        self._tree.clear()
        self._detail.setPlainText(placeholder)

    def reload_page(self) -> None:
        self.present(force=True)

    def _on_copy(self) -> None:
        clipboard: QClipboard = QApplication.clipboard()
        clipboard.setText(self._detail.toPlainText())

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        model: ContextNode | None = item.data(0, Qt.ItemDataRole.UserRole)
        if model is not None:
            self._populate_children(item, model)
            self.intent.expanded.add(model.key)

    def _on_collapsed(self, item: QTreeWidgetItem) -> None:
        model: ContextNode | None = item.data(0, Qt.ItemDataRole.UserRole)
        if model is not None:
            self.intent.expanded.discard(model.key)
