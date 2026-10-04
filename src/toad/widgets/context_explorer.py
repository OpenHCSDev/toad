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

    def search_current(self, query, selected):
        return self.query == query and self.selected is selected

    def rebind(self, original, model, show_detail):
        if self.selected is original:
            self.selected = model
            show_detail(model)

    def restore(self, nodes, restore_node):
        if self.selected is None:
            return False
        node = nodes.get(self.selected.key)
        if node is None:
            return False
        self.selected = node.data
        restore_node(node, self.selected)
        return True

    def with_selected(self, model, consume):
        if self.selected is model:
            consume(model)


class ContextTree(Tree[ContextNode]):
    """Native nodes, disclosure and cursor share the Tree's mounted lifetime."""

    def __init__(self, intent, show_detail, show_placeholder):
        self.intent = intent
        self.show_detail = show_detail
        self.show_placeholder = show_placeholder
        self.context_nodes = {}
        super().__init__("Context", id="context-tree")

    def clear(self):
        self.context_nodes.clear()
        return super().clear()

    def on_unmount(self):
        self.context_nodes.clear()

    def present(self, groups):
        # Reconcile the original TreeNodes so Tree._build rebases its cursor.
        with self.prevent(Tree.NodeExpanded, Tree.NodeCollapsed, Tree.NodeSelected,
                          Tree.NodeHighlighted):
            self.root.set_label("Context")
            self.root.expand()
            labels = {label for label, _, _ in groups}
            for node in tuple(self.root.children):
                if self.owns_node(node) or node.label.plain not in labels:
                    self._retire(node)
            for index, (label, models, expanded) in enumerate(groups):
                group = next((node for node in self.root.children
                              if node.label.plain == label), None)
                if group is None:
                    group = self.root.add(label, before=index, expand=expanded)
                self._reconcile(group, models)
        self.restore_reader("Select a context segment to inspect.")

    def search_results(self, matches, description, query):
        with self.prevent(Tree.NodeExpanded, Tree.NodeCollapsed, Tree.NodeSelected):
            self.clear()
            self.root.set_label(f"{description} · {query}")
            self.root.expand()
            for model in matches:
                self._add(self.root, model)
        self.restore_reader("Select a matching original source to read its full public text.")

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
                self.intent.rebind(original, model, self.show_detail)
            if node.label.plain != model.label:
                node.set_label(model.label)
            # Native disclosure remembers inspected empty leaves as well as
            # materialized children; unopened nodes remain lazy.
            if node.children or not node.allow_expand or node.is_expanded:
                self._reconcile(node, model.children())
                node.allow_expand = bool(node.children)
        for node in previous.values():
            self._retire(node)

    def _retire(self, node):
        for child in tuple(node.children):
            self._retire(child)
        if self.owns_node(node):
            self.context_nodes.pop(node.data.key)
        node.remove()

    def restore_reader(self, placeholder):
        with self.prevent(Tree.NodeExpanded, Tree.NodeCollapsed, Tree.NodeSelected):
            pending = list(self.context_nodes.values())
            while pending:
                node = pending.pop()
                if node.data.key in self.intent.expanded:
                    self._expand(node)
                    node.expand()
                    pending.extend(node.children)
        if not self.intent.restore(self.context_nodes, self._reveal_restored):
            self.show_placeholder(placeholder)

    def _reveal_restored(self, node, model):
        # Preserve an actual human cursor. Reveal only a rematerialized choice.
        if self.cursor_node is None:
            ancestor = node.parent
            with self.prevent(Tree.NodeExpanded):
                while ancestor is not None:
                    ancestor.expand()
                    ancestor = ancestor.parent
            self.call_after_refresh(self.intent.with_selected, model, self._restore_cursor)

    def _restore_cursor(self, model):
        node = self.context_nodes.get(model.key)
        if (self.owns_node(node) and node.data is model
                and (self.cursor_node is None or self.cursor_node is node)):
            with self.prevent(Tree.NodeHighlighted):
                self.move_cursor(node, animate=False)
            self.show_detail(model)

    def _add(self, parent, model, *, before=None):
        node = parent.add(model.label, model, before=before, allow_expand=True)
        self.context_nodes[model.key] = node
        return node

    def owns_node(self, node):
        if node is None:
            return False
        if node.data is None:
            return False
        return self.is_attached and self.context_nodes.get(node.data.key) is node

    def _expand(self, node):
        if not self.owns_node(node) or node.children:
            return
        # TreeNode owns whether this native disclosure still admits expansion.
        if node.allow_expand:
            for model in node.data.children():
                self._add(node, model)
            node.allow_expand = bool(node.children)

    @on(Tree.NodeExpanded, "#context-tree")
    def node_expanded(self, event):
        if self.owns_node(event.node):
            self.intent.expanded.add(event.node.data.key)
            self._expand(event.node)

    @on(Tree.NodeCollapsed, "#context-tree")
    def node_collapsed(self, event):
        if self.owns_node(event.node):
            self.intent.expanded.discard(event.node.data.key)

    def selected(self, model):
        return self.owns_node(self.cursor_node) and self.cursor_node.data is model


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

    def compose(self):
        yield Static("Context · select a segment to inspect", markup=False,
                     classes="context-status")
        yield Input(self.intent.query, placeholder="Search current context or selected recorded request · Enter",
                    id="context-search")
        with Horizontal(classes="context-controls"):
            yield Button("Search", id="context-find")
            yield Button("Read full", id="context-read-full")
            yield Button("Copy", id="context-copy")
        yield ContextTree(self.intent, self._show_detail, self._show_placeholder)
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
        self.state = InspectionState.for_owner(owner, root)
        self.intent.selected = None
        self.query_one(ContextTree).clear()
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

    def _show_placeholder(self, placeholder):
        self.query_one(TextArea).load_text(placeholder)

    def _present(self, captured: HoldingInspection):
        if self.intent.query:
            self._search(captured, self.intent.query, self.intent.selected)
            return
        self.workers.cancel_group(self, "context-search")
        self.query_one(ContextTree).present(captured.groups())

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
        description = selected.search_description() if selected is not None else "Current public context"
        self.query_one(ContextTree).search_results(matches, description, query)
        status.update(f"{len(matches)} matching sources · first 100 shown · {description}")

    def _searching(self, captured, query, selected):
        return (self._reading(captured) and self.state.search_current(captured)
                and self.intent.search_current(query, selected))

    @on(Button.Pressed, "#context-read-full")
    @work(group="context-full-read", exclusive=True, exit_on_error=False)
    async def action_read_full(self):
        node = self.query_one(ContextTree).cursor_node
        if not self.query_one(ContextTree).owns_node(node):
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
        node = self.query_one(ContextTree).cursor_node
        if self.query_one(ContextTree).owns_node(node):
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
        node = self.query_one(ContextTree).cursor_node
        if not self.query_one(ContextTree).owns_node(node):
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

    @on(Tree.NodeHighlighted, "#context-tree")
    def node_highlighted(self, event):
        event.stop()
        if self.query_one(ContextTree).owns_node(event.node):
            if self.intent.selected is not event.node.data:
                self.workers.cancel_group(self, "context-search")
            self.intent.selected = event.node.data
            self._show_detail(event.node.data)

    def _selected(self, model):
        return self.query_one(ContextTree).selected(model) if self.is_attached else False

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
