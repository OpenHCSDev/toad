"""A bounded, read-only Tree projection of the selected thread's context."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from acp.exceptions import RequestError
from textual import on, work
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Static, TextArea, Tree
from textual.worker import Worker, WorkerCancelled, WorkerState, get_current_worker
from agent_comms.mro_dispatch import handles

from toad.core.context_inspection import ContextInspection, ContextNode
from toad.core.events import CoordinationObserved, SessionSelected
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage
from toad.screens.session_view import SessionView
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SidebarVisibilityObserver


@dataclass
class ContextTreeIntent:
    """Only reader choices survive disposable sidebar widget retirement."""
    expanded: set[str] = field(default_factory=set)
    selected: str | None = None
    query: str = ""


class ContextExplorer(CoreEventReceiver, SidebarVisibilityObserver, Vertical):
    DEFAULT_CSS = """
    ContextExplorer { height: auto; }
    ContextExplorer > .context-status { height: auto; color: $text-muted; }
    ContextExplorer > Tree { height: 12; min-height: 4; }
    ContextExplorer > TextArea { height: 16; min-height: 6; border: none; }
    ContextExplorer > .context-controls { height: 3; }
    ContextExplorer > .context-controls Button { width: 1fr; min-width: 6; }
    ContextExplorer > Input { height: 3; }
    ContextExplorer > TextArea.-maximized { height: 1fr; width: 1fr; }
    """
    BINDINGS = [("r", "refresh", "Refresh context")]
    def __init__(self, owner: str, root: str | None, *, intent: ContextTreeIntent):
        super().__init__()
        self.owner, self.wire_root = owner, root
        self.intent = intent
        self._inspection: ContextInspection | None = None
        self._native = None
        self._observed_revision = None
        self._loaded: set[str] = set()
        self._context_nodes = {}

    def compose(self):
        yield Static("Context · select a segment to inspect", markup=False,
                     classes="context-status")
        yield Input(self.intent.query, placeholder="Search public instructions and messages · Enter",
                    id="context-search")
        with Horizontal(classes="context-controls"):
            yield Button("Search", id="context-find")
            yield Button("Read full", id="context-read-full")
            yield Button("Copy", id="context-copy")
        yield Tree[ContextNode]("Context", id="context-tree")
        yield TextArea("No context selected.", read_only=True, soft_wrap=True,
                       show_line_numbers=False, id="context-detail")
        yield Input(placeholder="Export to a new text file · path", id="context-export-path")
        yield Button("Export selected text + source", id="context-export")

    def on_mount(self):
        self.observe_core(self.app.coordination_access.events)
        self.observe_core(self.app.events)
        self.call_after_refresh(self.action_refresh)

    @handles(CoordinationObserved, SessionSelected)
    def context_changed(self, message: CoreEventMessage):
        self._observed()

    def presentation_visible(self):
        return (self.is_attached and self.query_ancestor(SessionView).is_current
                and not self.query_ancestor(SideBar).collapsed
                and not self.query_ancestor(SideBarCollapsible).collapsed)

    def on_show(self):
        self.call_after_refresh(self._observed)

    def sidebar_visibility_changed(self):
        self._observed()

    def _observed(self, _value=None):
        if not self.presentation_visible():
            return
        # Invalidation does not replace an original read still in flight.
        if self._working("context-read"):
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
        self.workers.cancel_node(self)
        self._context_nodes.clear()
        self._loaded.clear()
        self.owner, self.wire_root = owner, root
        self._inspection, self._native = None, None
        self._observed_revision = None
        self.query_one(Tree).clear()
        self.query_one(TextArea).load_text("No context selected.")
        self.action_refresh()

    def action_refresh(self):
        if self.presentation_visible():
            self._read(self.owner, self.wire_root, force=True)

    def _reading(self, owner, root):
        return (self.is_attached and not get_current_worker().is_cancelled
                and (owner, root) == (self.owner, self.wire_root))

    def _working(self, group):
        return any(worker.node is self and worker.group == group
                   and not worker.is_finished for worker in self.workers)

    @work(group="context-read", exclusive=True, exit_on_error=False)
    async def _read(self, owner, root, *, force=False):
        status = self.query_one(".context-status", Static)
        revision = self.app.coordination_access.revision
        self._observed_revision = revision
        if not owner or root is None:
            status.update("No managed thread context available")
            return
        try:
            service = self.app.coordination_access.service
            if str(service.root.resolve()) != str(root):
                status.update("Selected context belongs to another wire root")
                return
            inspection = await asyncio.to_thread(ContextInspection.read, service, owner)
            if not self._reading(owner, root):
                return
            previous = self._inspection
            same_source = (previous is not None
                           and inspection.same_native_source(previous))
            changed_manifests = (previous is None
                                 or inspection.manifests != previous.manifests)
            changed_contributors = False
            if same_source and self._native is not None:
                original = self._native
                refreshed = await asyncio.to_thread(
                    original.with_current_contributors, service, inspection.owner)
                if not self._reading(owner, root):
                    return
                if self._native is original:
                    changed_contributors = refreshed.contributors != original.contributors
                    if changed_contributors:
                        self._native = refreshed
            if not same_source:
                self.workers.cancel_group(self, "context-native")
                self._native = None
            self._inspection = inspection
            if not same_source or changed_manifests or changed_contributors:
                self._present(inspection, self._native)
            if force or not same_source:
                status.update(f"{owner} · recorded manifests available\nReading native context…")
                self._read_native(inspection, owner, root)
            elif (changed_manifests and self._native is None
                  and not self._working("context-native")):
                # An original SDK manifest is context evidence; an unrelated
                # roster status change is not permission to poll native again.
                self._read_native(inspection, owner, root)
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, RuntimeError, ConnectionError, RequestError) as error:
            if self._reading(owner, root):
                status.update(f"Context unavailable: {error}")

    @work(group="context-native", exclusive=True, exit_on_error=False)
    async def _read_native(self, inspection, owner, root):
        native = None
        unavailable = ""
        try:
            native = await inspection.native()
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, RuntimeError, ConnectionError, RequestError) as error:
            unavailable = str(error)
        if (not self._reading(owner, root) or self._inspection is None
                or not inspection.same_native_source(self._inspection)):
            return
        if native != self._native:
            self._native = native
            # Use the latest original manifest observation, not the earlier
            # capture whose native request was pending while it was appended.
            self._present(self._inspection, native)
        self.query_one(".context-status", Static).update(
            f"{owner} · current Core instructions and native base before future input/provider hooks\n"
            f"Segment counts: estimates ({native.counter}) · provider totals unavailable"
            if native is not None else
            f"{owner} · recorded manifests only\nCurrent detail unavailable: {unavailable}")

    def _present(self, inspection, native):
        if self.intent.query and native is not None:
            self._search(inspection, native, self.intent.query)
            return
        self.workers.cancel_group(self, "context-search")
        tree = self.query_one(Tree)
        self._context_nodes.clear()
        self._loaded.clear()
        with self.prevent(Tree.NodeExpanded, Tree.NodeCollapsed, Tree.NodeSelected):
            tree.clear()
            tree.root.set_label("Context")
            tree.root.expand()
            if native is not None:
                core = tree.root.add("Current Core instructions · before next input", expand=True)
                for model in inspection.contributors(native):
                    self._add(core, model)
                active = tree.root.add("Current native base · before next input and provider hooks", expand=True)
                for model in inspection.active(native):
                    self._add(active, model)
            recorded = tree.root.add("Recorded requests · source evidence, not today's base")
            for model in inspection.recorded():
                self._add(recorded, model)
        self._restore_reader("Select a context segment to inspect.")

    def _restore_reader(self, placeholder):
        with self.prevent(Tree.NodeExpanded, Tree.NodeCollapsed, Tree.NodeSelected):
            # Restore expansions without fetching referenced files or rebuilding text.
            pending = list(self._context_nodes.values())
            while pending:
                node = pending.pop()
                if node.data.key in self.intent.expanded:
                    self._expand(node)
                    node.expand()
                    pending.extend(node.children)
        if self.intent.selected in self._context_nodes:
            model = self._context_nodes[self.intent.selected].data
            self.call_after_refresh(self._restore_cursor, model)
        else:
            # A pending/unavailable original observation cannot revoke the
            # reader's choice. Reuse it when its node is materialized again.
            self.query_one(TextArea).load_text(placeholder)

    @on(Input.Changed, "#context-search")
    def query_changed(self, event):
        event.stop()
        self.intent.query = event.value

    @on(Input.Submitted, "#context-search")
    @on(Button.Pressed, "#context-find")
    def action_search(self, event):
        event.stop()
        if self._inspection is not None:
            self._present(self._inspection, self._native)
            if self._native is None and self.intent.query:
                self.query_one(".context-status", Static).update(
                    "Current public text is not loaded; search resumes when the native read completes.")

    @work(group="context-search", exclusive=True, exit_on_error=False)
    async def _search(self, inspection, native, query):
        status = self.query_one(".context-status", Static)
        status.update("Searching original public context…")
        try:
            matches = await asyncio.to_thread(inspection.find, native, query)
        except (OSError, ValueError, RuntimeError, RequestError) as error:
            if self._searching(inspection, native, query):
                status.update(f"Context search unavailable: {error}")
            return
        if not self._searching(inspection, native, query):
            return
        tree = self.query_one(Tree)
        self._context_nodes.clear()
        self._loaded.clear()
        with self.prevent(Tree.NodeExpanded, Tree.NodeCollapsed, Tree.NodeSelected):
            tree.clear()
            tree.root.set_label(f"Current public context · {query}")
            tree.root.expand()
            for model in matches:
                self._add(tree.root, model)
        status.update(f"{len(matches)} matching sources · first 100 shown · recorded request text is separate evidence")
        self._restore_reader("Select a matching original source to read its full public text.")

    def _searching(self, inspection, native, query):
        return (self.is_attached and not get_current_worker().is_cancelled
                and self._inspection is not None
                and inspection.same_native_source(self._inspection)
                and self._native is native
                and self.intent.query == query)

    @on(Button.Pressed, "#context-read-full")
    @work(group="context-full-read", exclusive=True, exit_on_error=False)
    async def action_read_full(self):
        node = self.query_one(Tree).cursor_node
        if not self._owns_node(node):
            return
        model = node.data
        try:
            await self._show_detail(model).wait()
        except WorkerCancelled:
            return
        if not self._selected(model):
            return
        detail = self.query_one(TextArea)
        self.screen.maximize(detail, container=False)
        detail.focus()

    @on(Button.Pressed, "#context-copy")
    @work(group="context-copy", exclusive=True, exit_on_error=False)
    async def action_copy(self):
        node = self.query_one(Tree).cursor_node
        if self._owns_node(node):
            model = node.data
            try:
                detail = await model.read()
            except (OSError, ValueError, RuntimeError, RequestError) as error:
                if self._selected(model):
                    self.notify(f"Context copy failed: {error}", severity="error")
                return
            if self._selected(model):
                self.app.copy_to_clipboard(detail)
                self.notify("Complete selected public text and source copied")

    @on(Button.Pressed, "#context-export")
    @work(group="context-export", exclusive=True, exit_on_error=False)
    async def action_export(self):
        node = self.query_one(Tree).cursor_node
        if not self._owns_node(node):
            return
        model = node.data
        destination = self.query_one("#context-export-path", Input).value.strip()
        if not destination:
            self.notify("Choose a new output file path", severity="warning")
            return
        try:
            await model.export(Path(destination).expanduser())
        except (OSError, ValueError, RuntimeError) as error:
            if self.is_attached:
                self.notify(f"Context export failed: {error}", severity="error")
        else:
            if self.is_attached:
                self.notify(f"Exported selected public text and source to {destination}")

    def _restore_cursor(self, model):
        node = self._context_nodes.get(model.key)
        if (self._owns_node(node) and node.data is model
                and self.intent.selected == model.key):
            # Restoring this exact reader choice owns its detail publication.
            # A second queued highlight must not cancel/re-read the same source.
            with self.prevent(Tree.NodeHighlighted):
                self.query_one(Tree).move_cursor(node, animate=False)
            self._show_detail(model)

    def _add(self, parent, model):
        node = parent.add(model.label, model, allow_expand=True)
        self._context_nodes[model.key] = node
        return node

    def _owns_node(self, node):
        return (self.is_attached and node is not None and node.data is not None
                and self._context_nodes.get(node.data.key) is node)

    def _expand(self, node):
        if not self._owns_node(node) or node.data.key in self._loaded:
            return
        self._loaded.add(node.data.key)
        for model in node.data.children():
            self._add(node, model)
        node.allow_expand = bool(node.children)

    @on(Tree.NodeExpanded, "#context-tree")
    def node_expanded(self, event):
        if self._owns_node(event.node):
            self.intent.expanded.add(event.node.data.key)
            self._expand(event.node)

    @on(Tree.NodeCollapsed, "#context-tree")
    def node_collapsed(self, event):
        if self._owns_node(event.node):
            self.intent.expanded.discard(event.node.data.key)

    @on(Tree.NodeHighlighted, "#context-tree")
    def node_highlighted(self, event):
        event.stop()
        if self._owns_node(event.node):
            self.intent.selected = event.node.data.key
            self._show_detail(event.node.data)

    def _selected(self, model):
        if not self.is_attached:
            return False
        node = self.query_one(Tree).cursor_node
        return node is not None and node.data is model and self._owns_node(node)

    @work(group="context-detail", exclusive=True, exit_on_error=False)
    async def _show_detail(self, model):
        # Publication belongs to this exact selected original tree model, not
        # a reusable string key shared by another thread or context snapshot.
        if not self._selected(model):
            return
        self.query_one(TextArea).load_text("Preparing selected context detail…")
        try:
            detail = await model.read()
        except (OSError, ValueError, RuntimeError, RequestError) as error:
            detail = f"Selected context detail unavailable: {error}"
        if self._selected(model):
            self.query_one(TextArea).load_text(detail)
