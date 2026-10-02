"""A bounded, read-only Tree projection of the selected thread's context."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from acp.exceptions import RequestError
from textual import on, work
from textual.containers import Vertical
from textual.widgets import Static, TextArea, Tree

from toad.context_inspection import ContextInspection, ContextNode
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
        access = self.app.coordination_access
        if self._observed_revision != access.revision or self._inspection is None:
            self._read(self.owner, self.wire_root)

    def set_identity(self, owner, root):
        if (owner, root) == (self.owner, self.wire_root):
            return
        self.workers.cancel_group(self, "context-read")
        self.owner, self.wire_root = owner, root
        self._inspection, self._native = None, None
        self._observed_revision = None
        self.query_one(Tree).clear()
        self.query_one(TextArea).load_text("No context selected.")
        self.action_refresh()

    def action_refresh(self):
        if self.visible():
            self._read(self.owner, self.wire_root, force=True)

    @work(group="context-read", exclusive=True, exit_on_error=False)
    async def _read(self, owner, root, *, force=False):
        status = self.query_one(".context-status", Static)
        if not owner or root is None:
            status.update("No managed thread context available")
            return
        service = self.app.coordination_access.service
        if str(service.root.resolve()) != str(root):
            status.update("Selected context belongs to another wire root")
            return
        revision = self.app.coordination_access.revision
        try:
            if (not force and self._inspection is not None
                    and await asyncio.to_thread(self._inspection.current, service)):
                self._observed_revision = revision
                return
            inspection = await asyncio.to_thread(ContextInspection.read, service, owner)
            native = None
            unavailable = ""
            try:
                native = await inspection.native(service)
            except (OSError, ValueError, RuntimeError, ConnectionError, RequestError) as error:
                unavailable = str(error)
            if (owner, root) != (self.owner, self.wire_root) or not self.is_attached:
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
                tree.select_node(self._context_nodes[selected])
        if selected in self._context_nodes:
            self._show_detail(self._context_nodes[selected].data)

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
        if event.node.data is not None:
            self.intent.selected = event.node.data.key
            self._show_detail(event.node.data)

    @work(group="context-detail", exclusive=True, exit_on_error=False)
    async def _show_detail(self, model):
        # JSON preparation and long body decoding stay off the UI thread.
        detail = await asyncio.to_thread(model.detail)
        if self.is_attached and self.intent.selected == model.key:
            if len(detail) > self.detail_characters:
                detail = detail[:self.detail_characters] + (
                    "\n\n[Preview truncated; original context remains unchanged.]")
            self.query_one(TextArea).load_text(detail)

    def on_unmount(self):
        self.workers.cancel_group(self, "context-read")
        self.workers.cancel_group(self, "context-detail")
