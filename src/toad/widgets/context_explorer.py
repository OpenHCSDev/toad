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

from toad.core.context_inspection import (
    ContextNode, DetachedInspection, HoldingInspection, InspectionState,
)
from toad.core.events import CoordinationObserved, SessionSelected
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage
from toad.screens.session_view import SessionView
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SidebarVisibilityObserver


@dataclass
class ContextTreeIntent:
    """Only reader choices survive disposable sidebar widget retirement."""
    expanded: set[str] = field(default_factory=set)
    selected: ContextNode | None = None
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
        self.state = InspectionState.for_owner(owner, root)
        self.intent = intent
        self._context_nodes = {}

    def compose(self):
        yield Static("Context · select a segment to inspect", markup=False,
                     classes="context-status")
        yield Input(self.intent.query, placeholder="Search current context or selected recorded request · Enter",
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
        if not self.state.observed_at(access.revision):
            self._read()

    @on(Worker.StateChanged)
    def context_read_finished(self, event):
        if (event.worker.node is self and event.worker.group == "context-read"
                and event.state == WorkerState.SUCCESS):
            self._observed()

    def on_unmount(self):
        self.state = DetachedInspection()

    def set_identity(self, owner, root):
        if self.state.bound_to(owner, root):
            return
        self.workers.cancel_node(self)
        self._context_nodes.clear()
        self.state = InspectionState.for_owner(owner, root)
        self.intent.selected = None
        self.query_one(Tree).clear()
        self.query_one(TextArea).load_text("No context selected.")
        self.action_refresh()

    def action_refresh(self):
        if self.presentation_visible():
            self._read(force=True)

    def _reading(self, captured):
        return (self.is_attached and not get_current_worker().is_cancelled
                and self.state.bound_to(captured.name, captured.root))

    def _working(self, group):
        return any(worker.node is self and worker.group == group
                   and not worker.is_finished for worker in self.workers)

    @work(group="context-read", exclusive=True, exit_on_error=False)
    async def _read(self, *, force=False):
        status = self.query_one(".context-status", Static)
        access = self.app.coordination_access
        previous = self.state
        self.state = previous.observe(access.revision)
        try:
            acquired = await self.state.acquire(access.service, access.revision)
            if not self._reading(previous):
                return
            self.state = self.state.receive_inspection(acquired)
            status.update(self.state.status)
            self.state.present(lambda current: self._inspection_acquired(previous, current, force))
            await self.state.refresh_contributors(self._contributors_acquired)
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, RuntimeError, ConnectionError, RequestError) as error:
            if self._reading(previous):
                status.update(f"Context unavailable: {error}")

    def _inspection_acquired(self, previous, current, force):
        if previous.inspection_differs(current.inspection):
            self._present(current)
        if previous.needs_native(current.inspection, force):
            source_changed = not previous.same_source(current.inspection)
            if source_changed:
                self.workers.cancel_group(self, "context-native")
            if force or source_changed or not self._working("context-native"):
                self.query_one(".context-status", Static).update(current.status)
                current.prepare_native(self._read_native)

    def _contributors_acquired(self, expected, native):
        updated = self.state.with_contributors(expected, native)
        if updated is not self.state:
            self.state = updated
            updated.present(self._present)

    @work(group="context-native", exclusive=True, exit_on_error=False)
    async def _read_native(self, captured: HoldingInspection):
        try:
            native = await captured.inspection.native()
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, RuntimeError, ConnectionError, RequestError) as error:
            if self._reading(captured):
                self._native_acquired(self.state.native_failed(captured.inspection, error))
        else:
            if self._reading(captured):
                self._native_acquired(self.state.with_native(captured.inspection, native))

    def _native_acquired(self, updated):
        if updated is not self.state:
            self.state = updated
            updated.present(self._present)
        self.query_one(".context-status", Static).update(updated.status)

    def _present(self, captured: HoldingInspection):
        if self.intent.query:
            self._search(captured, self.intent.query, self.intent.selected)
            return
        self.workers.cancel_group(self, "context-search")
        tree = self.query_one(Tree)
        groups = captured.groups()
        # Keep native TreeNodes: Tree._build rebases its cursor by node identity.
        # Contributor publication must not destroy an unrelated recorded reader.
        with self.prevent(Tree.NodeExpanded, Tree.NodeCollapsed, Tree.NodeSelected,
                          Tree.NodeHighlighted):
            tree.root.set_label("Context")
            tree.root.expand()
            labels = {label for label, _, _ in groups}
            for node in tuple(tree.root.children):
                if node.data is not None or node.label.plain not in labels:
                    self._retire(node)
            for index, (label, models, expanded) in enumerate(groups):
                group = next((node for node in tree.root.children
                              if node.label.plain == label), None)
                if group is None:
                    group = tree.root.add(label, before=index, expand=expanded)
                self._reconcile(group, models)
        self._restore_reader("Select a context segment to inspect.")

    def _reconcile(self, parent, models):
        previous = {node.data.key: node for node in parent.children}
        for index, model in enumerate(models):
            node = previous.pop(model.key, None)
            if node is None:
                self._add(parent, model, before=index)
                continue
            original = node.data
            if original != model:
                node.data = model
                if self.intent.selected is original:
                    self.intent.selected = model
                    self._show_detail(model)
            if node.label.plain != model.label:
                node.set_label(model.label)
            # Children and allow_expand own lazy materialization, including
            # an already-inspected empty leaf. No separate loaded-key roster.
            if node.children or not node.allow_expand or node.is_expanded:
                self._reconcile(node, model.children())
                node.allow_expand = bool(node.children)
        for node in previous.values():
            self._retire(node)

    def _retire(self, node):
        for child in tuple(node.children):
            self._retire(child)
        if node.data is not None:
            self._context_nodes.pop(node.data.key)
        node.remove()

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
        selected = self.intent.selected
        if selected is not None and selected.key in self._context_nodes:
            model = self._context_nodes[selected.key].data
            self.intent.selected = model
            # A rematerialized selected request still belongs to its original
            # Tree path. Reveal that path before moving its native cursor;
            # group disclosure is a rendering resource, not source authority.
            # A retained native cursor already belongs to human navigation.
            # Restore only after an actual projection replacement/remount.
            if self.query_one(Tree).cursor_node is None:
                ancestor = self._context_nodes[selected.key].parent
                with self.prevent(Tree.NodeExpanded):
                    while ancestor is not None:
                        ancestor.expand()
                        ancestor = ancestor.parent
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
        self.state.present(self._present)

    @work(group="context-search", exclusive=True, exit_on_error=False)
    async def _search(self, captured: HoldingInspection, query, selected):
        status = self.query_one(".context-status", Static)
        status.update("Searching original public context…")
        try:
            matches = await captured.find(query, selected)
        except (OSError, ValueError, RuntimeError, RequestError) as error:
            if self._searching(captured, query, selected):
                status.update(f"Context search unavailable: {error}")
            return
        if not self._searching(captured, query, selected):
            return
        tree = self.query_one(Tree)
        self._context_nodes.clear()
        with self.prevent(Tree.NodeExpanded, Tree.NodeCollapsed, Tree.NodeSelected):
            tree.clear()
            description = selected.search_description() if selected is not None else "Current public context"
            tree.root.set_label(f"{description} · {query}")
            tree.root.expand()
            for model in matches:
                self._add(tree.root, model)
        status.update(f"{len(matches)} matching sources · first 100 shown · {description}")
        self._restore_reader("Select a matching original source to read its full public text.")

    def _searching(self, captured, query, selected):
        return (self.is_attached and not get_current_worker().is_cancelled
                and self.state.search_current(captured)
                and self.intent.query == query
                and self.intent.selected is selected)

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
        tree = self.query_one(Tree)
        node = self._context_nodes.get(model.key)
        if (self._owns_node(node) and node.data is model
                and self.intent.selected is model
                and (tree.cursor_node is None or tree.cursor_node is node)):
            # Restoring this exact reader choice owns its detail publication.
            # A second queued highlight must not cancel/re-read the same source.
            with self.prevent(Tree.NodeHighlighted):
                tree.move_cursor(node, animate=False)
            self._show_detail(model)

    def _add(self, parent, model, *, before=None):
        node = parent.add(model.label, model, before=before, allow_expand=True)
        self._context_nodes[model.key] = node
        return node

    def _owns_node(self, node):
        return (self.is_attached and node is not None and node.data is not None
                and self._context_nodes.get(node.data.key) is node)

    def _expand(self, node):
        if not self._owns_node(node) or node.children or not node.allow_expand:
            return
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
            if self.intent.selected is not event.node.data:
                self.workers.cancel_group(self, "context-search")
            self.intent.selected = event.node.data
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
