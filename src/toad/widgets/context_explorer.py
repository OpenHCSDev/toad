"""A bounded, read-only Tree projection of the selected thread's context."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from acp.exceptions import RequestError
from agent_comms.context_store import ContextManifestCursor
from agent_comms.coordinator import Coordination
from agent_comms.mro_dispatch import handles
from agent_comms.route_selection import RouteSelection
from textual import on, work
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Static, Tree
from textual.widgets._tree import TreeNode
from textual.worker import Worker, WorkerCancelled, WorkerState, get_current_worker

from toad.core.context_inspection import (
    ContextNode,
    DetachedInspection,
    HoldingInspection,
    InspectionState,
)
from toad.core.events import CoordinationObserved, SessionSelected
from toad.core_event_carrier import CoreEventMessage
from toad.screens.session_view import SessionView
from toad.thread_identity import SessionIdentity, ThreadIdentity
from toad.widgets.process_text_area import ProcessTextArea
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SidebarVisibilityObserver
from toad.widgets.thread_identity import ShowsThreadIdentity


@dataclass
class ContextTreeIntent:
    """Detail selection and initial disclosures survive widget retirement.

    The mounted Tree owns navigation; selected is the detail source, not its cursor.
    """
    expanded: set[str] = field(default_factory=set)
    selected: ContextNode | None = None
    query: str = ""
    cursor: ContextManifestCursor | None = None

    def select_page(self, cursor) -> bool:
        if cursor is None:
            return False
        self.cursor = cursor
        self.selected = None
        return True

    def search_current(self, query, selected):
        return self.query == query and self.selected is selected

    def rebind(self, original, model) -> None:
        if self.selected is original:
            self.selected = model

    def restore_detail(self, resolve, show_detail) -> bool:
        if self.selected is None:
            return False
        node = resolve(self.selected.key)
        if node is None:
            return False
        self.selected = node.data
        show_detail(self.selected)
        return True


class ContextTree(Tree[ContextNode]):
    """Native nodes, disclosure and cursor share the Tree's mounted lifetime."""

    def __init__(self, show_detail: Callable[..., Worker[None]], show_placeholder) -> None:
        self.show_detail = show_detail
        self.show_placeholder = show_placeholder
        self.context_nodes = {}
        super().__init__("Context", id="context-tree")
        with self.prevent(Tree.NodeExpanded):
            self.root.expand()

    @property
    def intent(self):
        return self.query_ancestor(ContextExplorer).intent

    def clear(self):
        self.context_nodes.clear()
        return super().clear()

    def on_unmount(self) -> None:
        self.context_nodes.clear()

    def present(self, groups) -> None:
        # Reconcile the original TreeNodes so Tree._build rebases its cursor.
        with self.prevent(Tree.NodeExpanded, Tree.NodeCollapsed, Tree.NodeSelected,
                          Tree.NodeHighlighted):
            self.root.set_label("Context")
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
        self.restore_detail("Select a context segment to inspect.")

    def search_results(self, matches, description: str, query) -> None:
        with self.prevent(Tree.NodeExpanded, Tree.NodeCollapsed, Tree.NodeSelected):
            self.clear()
            self.root.set_label(f"{description} · {query}")
            self.root.expand()
            for model in matches:
                self._add(self.root, model)
        self.restore_detail("Select a matching original source to read its full public text.")

    def _reconcile(self, parent, models) -> None:
        previous = {node.data.key: node for node in parent.children}
        for index, model in enumerate(models):
            node = previous.pop(model.key, None)
            if node is None:
                self._add(parent, model, before=index)
                continue
            original = node.data
            # The original coordinate already selected the native node above.
            # Bind the newly acquired reader instead of recursively comparing
            # its complete inspection and all recorded requests on the UI loop.
            if original is not model:
                node.data = model
                self.intent.rebind(original, model)
            if node.label.plain != model.label:
                node.set_label(model.label)
            # Native disclosure remembers inspected empty leaves as well as
            # materialized children; unopened nodes remain lazy.
            if node.children or not node.allow_expand or node.is_expanded:
                self._reconcile(node, model.children())
                node.allow_expand = bool(node.children)
        for node in previous.values():
            self._retire(node)

    def _retire(self, node) -> None:
        for child in tuple(node.children):
            self._retire(child)
        if self.owns_node(node):
            self.context_nodes.pop(node.data.key)
        node.remove()

    def restore_detail(self, placeholder: str) -> None:
        if not self.intent.restore_detail(self.resolve_reader, self.show_detail):
            self.show_placeholder(placeholder)

    def resolve_reader(self, key):
        """Rebind the detail source without changing native navigation."""
        node = self.context_nodes.get(key)
        if node is None:
            for root in tuple(self.context_nodes.values()):
                path = root.data.reader_path(key)
                if not path:
                    continue
                node = root
                for model in path[1:]:
                    self._expand(node)
                    node = self.context_nodes[model.key]
                break
        return node

    def _add(self, parent: TreeNode[ContextNode], model, *, before=None):
        node = parent.add(model.label, model, before=before, allow_expand=True,
                          expand=model.key in self.intent.expanded)
        self.context_nodes[model.key] = node
        if node.is_expanded:
            self._expand(node)
        return node

    def owns_node(self, node):
        if node is None:
            return False
        if node.data is None:
            return False
        return self.is_attached and self.context_nodes.get(node.data.key) is node

    def _expand(self, node) -> None:
        if not self.owns_node(node) or node.children:
            return
        # TreeNode owns whether this native disclosure still admits expansion.
        if node.allow_expand:
            for model in node.data.children():
                self._add(node, model)
            node.allow_expand = bool(node.children)

    def _toggle_node(self, node) -> None:
        # Capture disclosure navigation before collapsing a selected descendant.
        # Data-less groups are native rows too; they don't select detail sources.
        with self.prevent(Tree.NodeHighlighted):
            self.move_cursor(node, animate=False)
        super()._toggle_node(node)

    @on(Tree.NodeExpanded, "#context-tree")
    def node_expanded(self, event) -> None:
        if self.owns_node(event.node):
            self.intent.expanded.add(event.node.data.key)
            self._expand(event.node)

    @on(Tree.NodeCollapsed, "#context-tree")
    def node_collapsed(self, event) -> None:
        if self.owns_node(event.node):
            self.intent.expanded.discard(event.node.data.key)

    def selected(self, model):
        node = self.context_nodes.get(model.key)
        return (self.owns_node(node) and node.data is model
                and self.intent.selected is model)


class ContextExplorer(ShowsThreadIdentity, SidebarVisibilityObserver, Vertical):
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
    def __init__(self, *, intents: dict[SessionIdentity, ContextTreeIntent]) -> None:
        super().__init__()
        self.state: InspectionState = DetachedInspection()
        self._intents = intents
        self.search_field = Input(placeholder="Search current context or selected recorded request · Enter",
                                  id="context-search")

    @property
    def intent(self) -> ContextTreeIntent:
        return self._intents.setdefault(self.thread_view.thread_identity, ContextTreeIntent())

    def compose(self):
        yield Static("Context · select a segment to inspect", markup=False,
                     classes="context-status")
        self.search_field.value = self.intent.query
        yield self.search_field
        with Horizontal(classes="context-controls"):
            yield Button("Search", id="context-find")
            yield Button("Read full", id="context-read-full")
            yield Button("Copy", id="context-copy")
            yield Button("Correct", id="context-correct")
        with Horizontal(classes="context-controls"):
            yield Button("Newer requests", id="context-newer", disabled=True)
            yield Button("Older requests", id="context-older", disabled=True)
        yield ContextTree(self._show_detail, self._show_placeholder)
        yield ProcessTextArea("No context selected.", soft_wrap=True,
                       show_line_numbers=False, id="context-detail")
        yield Input(placeholder="Export to a new text file · path", id="context-export-path")
        yield Button("Export selected text + source", id="context-export")

    def on_mount(self) -> None:
        self.observe_core(self.app.coordination_access.events)
        self.observe_core(self.app.events)
        self.call_after_refresh(self.action_refresh)

    @handles(CoordinationObserved, SessionSelected)
    def context_changed(self, message: CoreEventMessage) -> None:
        self._observed()

    def presentation_visible(self):
        return (self.is_attached and self.query_ancestor(SessionView).is_current
                and not self.query_ancestor(SideBar).collapsed
                and not self.query_ancestor(SideBarCollapsible).collapsed)

    def on_show(self) -> None:
        self.call_after_refresh(self._observed)

    def sidebar_visibility_changed(self) -> None:
        self._observed()

    def _observed(self, _value=None) -> None:
        if not self.presentation_visible():
            return
        # Invalidation does not replace an original read still in flight.
        if self._working("context-read"):
            return
        access = self.app.coordination_access
        if not self.state.observed_at(access.revision):
            self._read()

    @on(Worker.StateChanged)
    def context_read_finished(self, event) -> None:
        if (event.worker.node is self and event.worker.group == "context-read"
                and event.state == WorkerState.SUCCESS):
            self._observed()

    def on_unmount(self) -> None:
        self.state = DetachedInspection()

    def identity_changed(self, identity: SessionIdentity) -> None:
        self.workers.cancel_node(self)
        self.state = identity.inspection_state()
        self.search_field.value = self.intent.query
        self.query_one(ContextTree).clear()
        self.query_one(".context-status", Static).update(f"Context · {identity.display_thread()}")
        self._show_placeholder("No context selected.")
        self.action_refresh()

    def action_refresh(self) -> None:
        if self.presentation_visible():
            self._read(force=True)

    def _reading(self, identity: SessionIdentity):
        return (self.is_attached and not get_current_worker().is_cancelled
                and self.thread_view.thread_identity == identity)

    def _working(self, group: str):
        return any(worker.node is self and worker.group == group
                   and not worker.is_finished for worker in self.workers)

    @work(group="context-read", exclusive=True)
    async def _read(self, *, force: bool=False) -> None:
        await self.thread_view.thread_identity.inspect_owner(
            lambda identity: self._read_owner(identity, force=force),
            self.query_one(".context-status", Static).update)

    async def _read_owner(self, identity: ThreadIdentity, *, force: bool=False):
        status = self.query_one(".context-status", Static)
        access = self.app.coordination_access
        previous = self.state
        self.state = previous.observe(access.revision)
        try:
            service = await self.app.preparation.run_thread(
                lambda: access.require(RouteSelection.capture(identity.root_path())).service)
            if not self._reading(identity):
                return
            acquired = await self.state.acquire(service, access.revision, identity,
                cursor=self.intent.cursor)
            if not self._reading(identity):
                return
            self.state = self.state.receive_inspection(acquired)
            status.update(self.state.status)
            self.state.present(lambda current: self._inspection_acquired(previous, current, force))
        except asyncio.CancelledError:
            raise

    def _inspection_acquired(self, previous: InspectionState, current, force: bool) -> None:
        self.query_one("#context-older", Button).disabled = not current.inspection.page.has_older()
        self.query_one("#context-newer", Button).disabled = not current.inspection.page.has_newer()
        if previous.inspection_differs(current.inspection):
            current.present_acquired(previous, self._present)
        if previous.needs_native(current.inspection, force):
            source_changed = not previous.same_source(current.inspection)
            if source_changed:
                self.workers.cancel_group(self, "context-native")
            if force or source_changed or not self._working("context-native"):
                self.query_one(".context-status", Static).update(current.status)
                current.prepare_native(self._read_native)

    @work(group="context-native", exclusive=True)
    async def _read_native(self, captured: HoldingInspection):
        try:
            native = await captured.inspection.native()
        except asyncio.CancelledError:
            raise
        except RequestError as error:
            if self._reading(captured.thread_identity):
                self._native_acquired(self.state.native_failed(captured.inspection, error))
        else:
            if self._reading(captured.thread_identity):
                self._native_acquired(self.state.with_native(captured.inspection, native))

    def _native_acquired(self, updated: InspectionState) -> None:
        if updated is not self.state:
            self.state = updated
            updated.present(self._present)
        self.query_one(".context-status", Static).update(updated.status)

    def _show_placeholder(self, placeholder: str) -> None:
        detail = self.query_one(ProcessTextArea)
        detail.load_text_prepared(placeholder)

    @on(Button.Pressed, "#context-correct")
    def action_correct(self, event) -> None:
        from functools import partial

        from toad.widgets.comms_menu import show_target_menu

        event.stop()
        node = self.query_one(ContextTree).cursor_node
        if not self.query_one(ContextTree).owns_node(node):
            return
        model = node.data
        answers = model.correction_answers()
        if not answers:
            self.notify("Select an original annotation to correct", severity="warning")
            return
        show_target_menu(self.screen, event.button.region.offset, "Correct original answer",
            [(answer.declared_name, answer.public_title()) for answer in answers],
            {answer.declared_name: partial(self._correct_annotation, model, answer)
             for answer in answers})

    @work(group="context-correction", exclusive=True)
    async def _correct_annotation(self, model, answer) -> None:
        if not self._selected(model):
            return
        worktree = self.query_ancestor(SessionView).project_root
        await model.correct(answer, worktree)
        if self._selected(model):
            self.notify("Original human correction recorded")
            self._read()

    @work(group="context-presentation", exclusive=True)
    async def _present(self, captured: HoldingInspection) -> None:
        if self.intent.query:
            self._search(captured, self.intent.query, self.intent.selected)
            return
        self.workers.cancel_group(self, "context-search")
        # The acquired inspection owns its source projection. Building all
        # recorded segments and annotation relationships is preparation, not
        # a native Tree operation; keep it off the application's input loop.
        groups = await Coordination.run_worker(captured.groups)
        # Parking retains this tree and its workers. Publish valid preparation
        # into that original tree even while hidden; unmount/identity changes
        # and new source/native resources still revoke the captured content.
        if (self._reading(captured.thread_identity) and self.state.presentation_current(captured)
                and not self.intent.query):
            self.query_one(ContextTree).present(groups)

    @on(Button.Pressed, "#context-older")
    def older_requests(self, event) -> None:
        event.stop()
        self.state.present(self._older_requests)

    def _older_requests(self, current) -> None:
        if self.intent.select_page(current.inspection.page.older):
            self._change_page()

    @on(Button.Pressed, "#context-newer")
    def newer_requests(self, event) -> None:
        event.stop()
        self.state.present(self._newer_requests)

    def _newer_requests(self, current) -> None:
        if self.intent.select_page(current.inspection.page.newer):
            self._change_page()

    def _change_page(self) -> None:
        # Destination selection ends the acquired page's lifetime now, not
        # when the replacement read finishes. Unacquired inspection states
        # cannot publish old groups, searches or native results.
        self.state = self.thread_view.thread_identity.inspection_state()
        self.workers.cancel_group(self, "context-presentation")
        self.workers.cancel_group(self, "context-native")
        self.workers.cancel_group(self, "context-search")
        self.workers.cancel_group(self, "context-detail")
        self.query_one("#context-older", Button).disabled = True
        self.query_one("#context-newer", Button).disabled = True
        self.query_one(ContextTree).clear()
        self._show_placeholder("Loading recorded request page…")
        self._read()

    @on(Input.Changed, "#context-search")
    def query_changed(self, event) -> None:
        event.stop()
        self.intent.query = event.value

    @on(Input.Submitted, "#context-search")
    @on(Button.Pressed, "#context-find")
    def action_search(self, event) -> None:
        event.stop()
        self.state.present(self._present)

    @work(group="context-search", exclusive=True)
    async def _search(self, captured: HoldingInspection, query: str, selected: ContextNode | None) -> None:
        status = self.query_one(".context-status", Static)
        status.update("Searching original public context…")
        matches = await captured.find(query, selected)
        if not self._searching(captured, query, selected):
            return
        description = selected.search_description() if selected is not None else "Current public context"
        self.query_one(ContextTree).search_results(matches, description, query)
        status.update(f"{len(matches)} matching sources · first 100 shown · {description}")

    def _searching(self, captured: HoldingInspection, query, selected):
        return (self._reading(captured.thread_identity) and self.state.presentation_current(captured)
                and self.intent.search_current(query, selected))

    @on(Button.Pressed, "#context-read-full")
    @work(group="context-full-read", exclusive=True)
    async def action_read_full(self) -> None:
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
        detail = self.query_one(ProcessTextArea)
        self.screen.maximize(detail, container=False)
        detail.focus()

    @on(Button.Pressed, "#context-copy")
    @work(group="context-copy", exclusive=True)
    async def action_copy(self) -> None:
        node = self.query_one(ContextTree).cursor_node
        if self.query_one(ContextTree).owns_node(node):
            model = node.data
            detail = await model.read()
            if self._selected(model):
                self.app.copy_to_clipboard(detail)
                self.notify("Complete selected public text and source copied")

    @on(Button.Pressed, "#context-export")
    @work(group="context-export", exclusive=True)
    async def action_export(self) -> None:
        node = self.query_one(ContextTree).cursor_node
        if not self.query_one(ContextTree).owns_node(node):
            return
        model = node.data
        destination = self.query_one("#context-export-path", Input).value.strip()
        if not destination:
            self.notify("Choose a new output file path", severity="warning")
            return
        await model.export(Path(destination).expanduser())
        if self.is_attached:
            self.notify(f"Exported selected public text and source to {destination}")

    @on(Tree.NodeHighlighted, "#context-tree")
    def node_highlighted(self, event) -> None:
        event.stop()
        if self.query_one(ContextTree).owns_node(event.node):
            if self.intent.selected is not event.node.data:
                self.workers.cancel_group(self, "context-search")
            self.intent.selected = event.node.data
            self._show_detail(event.node.data)

    def _selected(self, model):
        return self.query_one(ContextTree).selected(model) if self.is_attached else False

    @work(group="context-detail", exclusive=True)
    async def _show_detail(self, model) -> None:
        # Publication belongs to this exact selected original tree model, not
        # a reusable string key shared by another thread or context snapshot.
        if not self._selected(model):
            return
        area = self.query_one(ProcessTextArea)
        # A read borrows the native document; it does not replace the reader's
        # selection and scroll with a temporary one-line document.
        detail = await model.read()
        if self._selected(model):
            # A new authenticated node may supply identical displayed text.
            # Its source is still read above; unchanged native answers need
            # neither document reconstruction nor a cursor/reader reset.
            await area.load_text_prepared(detail).wait()
