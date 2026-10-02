"""A bounded, read-only Tree projection of the selected thread's context."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from acp.exceptions import RequestError
from textual import on, work
from textual.containers import Vertical
from textual.widgets import Static, TextArea, Tree
from textual.worker import Worker, WorkerState, get_current_worker

from toad.core.context_inspection import ContextInspection, ContextNode
from toad.screens.session_view import SessionView
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SidebarVisibilityObserver


@dataclass
class ContextTreeIntent:
    """Only reader choices survive disposable sidebar widget retirement."""
    expanded: set[str] = field(default_factory=set)
    selected: str | None = None


class ContextExplorer(SidebarVisibilityObserver, Vertical):
    DEFAULT_CSS = """
    ContextExplorer { height: auto; }
    ContextExplorer > .context-status { height: auto; color: $text-muted; }
    ContextExplorer > Tree { height: 12; min-height: 4; }
    ContextExplorer > TextArea { height: 8; min-height: 3; border: none; }
    """
    BINDINGS = [("r", "refresh", "Refresh context")]
    DETAIL_CHARACTERS = 24000

    def __init__(self, owner: str, root: str | None, *, intent: ContextTreeIntent,
                 detail_characters: int = DETAIL_CHARACTERS):
        super().__init__()
        self.owner, self.wire_root = owner, root
        self.intent = intent
        if detail_characters < 1:
            raise ValueError("Context detail preview must have a positive bound")
        self.detail_characters = detail_characters
        self._inspection: ContextInspection | None = None
        self._native = None
        self._observed_revision = None
        self._loaded: set[str] = set()
        self._context_nodes = {}

    def compose(self):
        yield Static("Context · select a segment to inspect", markup=False,
                     classes="context-status")
        yield Tree[ContextNode]("Context", id="context-tree")
        yield TextArea("No context selected.", read_only=True, soft_wrap=True,
                       show_line_numbers=False, id="context-detail")

    def on_mount(self):
        self.app.coordination_observed.subscribe(self, self._observed)
        self.app.session_selected_signal.subscribe(self, self._observed)
        self.call_after_refresh(self.action_refresh)

    def visible(self):
        return (self.is_attached and self.query_ancestor(SessionView).is_current
                and not self.query_ancestor(SideBar).collapsed
                and not self.query_ancestor(SideBarCollapsible).collapsed)

    def on_show(self):
        self.call_after_refresh(self._observed)

    def sidebar_visibility_changed(self):
        self._observed()

    def _observed(self, _value=None):
        if not self.visible():
            return
        # Invalidation does not replace an original read still in flight.
        if any(worker.node is self and worker.group == "context-read"
               and not worker.is_finished for worker in self.workers):
            return
        access = self.app.coordination_access
        if self._observed_revision != access.revision:
            self._read(self.owner, self.wire_root)

    @on(Worker.StateChanged)
    def context_read_finished(self, event):
        if (event.worker.node is self and event.worker.group == "context-read"
                and event.state == WorkerState.SUCCESS):
            self._observed()

    def set_identity(self, owner, root):
        if (owner, root) == (self.owner, self.wire_root):
            return
        self.workers.cancel_group(self, "context-read")
        self.workers.cancel_group(self, "context-detail")
        self._context_nodes.clear()
        self._loaded.clear()
        self.owner, self.wire_root = owner, root
        self._inspection, self._native = None, None
        self._observed_revision = None
        self.query_one(Tree).clear()
        self.query_one(TextArea).load_text("No context selected.")
        self.action_refresh()

    def action_refresh(self):
        if self.visible():
            self._read(self.owner, self.wire_root, force=True)

    def _reading(self, owner, root):
        return (self.is_attached and not get_current_worker().is_cancelled
                and (owner, root) == (self.owner, self.wire_root))

    @work(group="context-read", exclusive=True, exit_on_error=False)
    async def _read(self, owner, root, *, force=False):
        status = self.query_one(".context-status", Static)
        revision = self.app.coordination_access.revision
        self._observed_revision = revision
        if not owner or root is None:
            status.update("No managed thread context available")
            return
        service = self.app.coordination_access.service
        if str(service.root.resolve()) != str(root):
            status.update("Selected context belongs to another wire root")
            return
        try:
            if (not force and self._inspection is not None
                    and await asyncio.to_thread(self._inspection.current, service)):
                if self._reading(owner, root):
                    self._observed_revision = revision
                return
            inspection = await asyncio.to_thread(ContextInspection.read, service, owner)
            if not self._reading(owner, root):
                return
            if self._inspection is None:
                self._present(inspection, None)
                status.update(f"{owner} · recorded manifests available\nReading native context…")
            native = None
            unavailable = ""
            try:
                native = await inspection.native(service)
            except (OSError, ValueError, RuntimeError, ConnectionError, RequestError) as error:
                unavailable = str(error)
            if not self._reading(owner, root):
                return
            self._observed_revision = revision
            if inspection == self._inspection and native == self._native:
                return
            self._inspection, self._native = inspection, native
            self._present(inspection, native)
            status.update(
                f"{owner} · native base before future input/provider hooks\n"
                f"Segment counts: estimates ({native.counter}) · provider totals unavailable"
                if native is not None else
                f"{owner} · recorded manifests only\nCurrent detail unavailable: {unavailable}")
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, RuntimeError, ConnectionError, RequestError) as error:
            if self._reading(owner, root):
                self._observed_revision = revision
                status.update(f"Context unavailable: {error}")

    def _present(self, inspection, native):
        tree = self.query_one(Tree)
        selected = self.intent.selected
        self._context_nodes.clear()
        self._loaded.clear()
        with self.prevent(Tree.NodeExpanded, Tree.NodeCollapsed, Tree.NodeSelected):
            tree.clear()
            tree.root.expand()
            if native is not None:
                active = tree.root.add("Active native context", expand=True)
                for model in inspection.active(native):
                    self._add(active, model)
            recorded = tree.root.add("Recorded turns · not added to active totals")
            for model in inspection.recorded():
                self._add(recorded, model)
            tree.root.add_leaf("Archived context: not supplied by this observation")
            # Restore expansions without fetching referenced files or rebuilding text.
            pending = list(self._context_nodes.values())
            while pending:
                node = pending.pop()
                if node.data.key in self.intent.expanded:
                    self._expand(node)
                    node.expand()
                    pending.extend(node.children)
        if selected in self._context_nodes:
            model = self._context_nodes[selected].data
            self.call_after_refresh(self._restore_cursor, model)
        else:
            self.intent.selected = None
            self.query_one(TextArea).load_text("Select a context segment to inspect.")

    def _restore_cursor(self, model):
        node = self._context_nodes.get(model.key)
        if (self.is_attached and node is not None and node.data is model
                and self.intent.selected == model.key):
            self.query_one(Tree).move_cursor(node, animate=False)
            self._show_detail(model)

    def _add(self, parent, model):
        node = parent.add(model.label, model, allow_expand=True)
        self._context_nodes[model.key] = node
        return node

    def _expand(self, node):
        if node.data is None or node.data.key in self._loaded:
            return
        self._loaded.add(node.data.key)
        for model in node.data.children():
            self._add(node, model)
        node.allow_expand = bool(node.children)

    @on(Tree.NodeExpanded, "#context-tree")
    def node_expanded(self, event):
        if event.node.data is not None:
            self.intent.expanded.add(event.node.data.key)
            self._expand(event.node)

    @on(Tree.NodeCollapsed, "#context-tree")
    def node_collapsed(self, event):
        if event.node.data is not None:
            self.intent.expanded.discard(event.node.data.key)

    @on(Tree.NodeSelected, "#context-tree")
    @on(Tree.NodeHighlighted, "#context-tree")
    def node_selected(self, event):
        event.stop()
        if (event.node.data is not None
                and self._context_nodes.get(event.node.data.key) is event.node):
            self.intent.selected = event.node.data.key
            self._show_detail(event.node.data)

    def _selected(self, model):
        if not self.is_attached:
            return False
        node = self.query_one(Tree).cursor_node
        return (node is not None and node.data is model
                and self._context_nodes.get(model.key) is node)

    @work(group="context-detail", exclusive=True, exit_on_error=False)
    async def _show_detail(self, model):
        # Publication belongs to this exact selected original tree model, not
        # a reusable string key shared by another thread or context snapshot.
        if not self._selected(model):
            return
        self.query_one(TextArea).load_text("Preparing selected context detail…")
        try:
            detail = await asyncio.to_thread(model.detail)
        except (OSError, ValueError, RuntimeError, RequestError) as error:
            detail = f"Selected context detail unavailable: {error}"
        if self._selected(model):
            if len(detail) > self.detail_characters:
                detail = detail[:self.detail_characters] + (
                    "\n\n[Preview truncated; original context remains unchanged.]")
            self.query_one(TextArea).load_text(detail)

    def on_unmount(self):
        self.workers.cancel_group(self, "context-read")
        self.workers.cancel_group(self, "context-detail")
