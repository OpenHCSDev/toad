"""Isolated, typed fixture for the right Comms tree; no new core service needed."""

import asyncio
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

from textual.app import App, ComposeResult
from textual.signal import Signal
from toad.session_tracker import SidebarState
from toad.widgets.comms_sidebar import CommsRow, SelectTarget
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.sidebar_tree import TargetTree
from toad.widgets.thread_comms import RelationshipSort, ThreadCommsSidebar
from toad.widgets.thread_comms_source import WireRelationshipSource

from agent_comms import Activity, ActivityState, Comms, Thread, ThreadSort, ThreadStatus, ThreadView


@dataclass(frozen=True)
class Entry:
    target: str
    kind: str
    person: ThreadView | None = None
    sequence: int = 0
    timestamp: float = 0
    detail: str = ""
    available: bool = True


@dataclass(frozen=True)
class Group:
    key: str
    title: str
    entries: tuple[Entry, ...]
    order: ThreadSort | None = None


@dataclass(frozen=True)
class Snapshot:
    owner: str
    root: str
    groups: tuple[Group, ...]
    history_limited: bool = False
    history_messages: int = 3
    incoming_basis: str = "Fixture routes (not a live wire)"


class FixtureSource:
    def __init__(self, root):
        self.root = str(root)
        self.version = 1
        self.reads = 0
        self.order = {"children": ThreadSort.CREATED, "collaborating": ThreadSort.LAST_ACTIVITY}
        self.people = {
            name: ThreadView(Thread(name, frozenset(), self.root, created_at=index + 1,
                                    session_file=f"{root}/{name}.jsonl"),
                             ThreadStatus.RUNNING,
                             Activity(name, ActivityState.THINKING if index % 2
                                      else ActivityState.IDLE,
                                      "Reviewing sidebar changes" if index % 2 else "",
                                      index + 1), None, 0)
            for index, name in enumerate(["origin", "peer", *[f"child-{i:02}" for i in range(12)]])
        }

    def revision(self):
        return self.version

    def snapshot(self, owner):
        self.reads += 1
        def entry(name):
            return Entry(name, "thread", self.people[name])
        children = tuple(entry(name) for name in self.people if name.startswith("child-"))
        order = self.order["children"]
        children = tuple(sorted(children, key=lambda row: order.key(
            row.target, row.person.thread.created_at, row.person.activity.timestamp, 0)))
        return Snapshot(owner, self.root, (
            Group("inbound", "Last inbound", (entry("peer"), Entry("#team", "channel"))),
            Group("outbound", "Last outbound", (Entry("#team", "channel"),)),
            Group("parent", "Parent fork", (entry("origin"),)),
            Group("children", "Children", children, order),
            Group("collaborating", "Collaborating", (entry("peer"),), self.order["collaborating"]),
        ))

    def set_order(self, owner, group, order):
        self.order[group] = order
        self.version += 1
        return order


class ReferenceTree(TargetTree):
    def __init__(self, source):
        super().__init__()
        self.source = source
        self.selected = ""
        self._cursor = 0

    def compose(self):
        row = CommsRow("thread", "peer", "peer")
        row.update_thread(self.source.people["peer"], unread=22)
        yield row

    def _ordered_rows(self):
        return list(self.query(CommsRow))

    def remember_row(self, row):
        self.selected = row.target_name


class FixtureApp(App):
    CSS = "Screen { layout: horizontal; } #reference { width: 40; }"

    def __init__(self, source):
        super().__init__()
        self.source = source
        self.pending_thread_actions = {}
        self.coordination_wire = SimpleNamespace(root=Path(source.root))
        self._sidebar_snapshot = SimpleNamespace(thread_unread={"peer": 22}, unread={})
        self.coordination_observed = Signal(self, "fixture-observed")
        self.open_tabs_changed = Signal(self, "fixture-tabs")
        self.mode_change_signal = Signal(self, "fixture-mode")
        self.thread_actions_changed = Signal(self, "fixture-actions")
        self.opened = []

    def compose(self) -> ComposeResult:
        yield ReferenceTree(self.source)
        yield SideBar(SideBar.Panel(
            "Comms", ThreadCommsSidebar("owner", wire_root=self.source.root, source=self.source),
            collapsed=True, id="comms-panel", header_control=RelationshipSort()),
            right=True, navigation=SidebarState())

    def on_select_target(self, event: SelectTarget):
        self.opened.append((event.target, event.kind))


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-right-comms-") as directory:
        source = FixtureSource(Path(directory))
        app = FixtureApp(source)
        async with app.run_test(size=(120, 42)) as pilot:
            await pilot.pause()
            tree = app.query_one(ThreadCommsSidebar)
            panel = tree.query_ancestor(SideBarCollapsible)
            assert source.reads == 0, "Collapsed panel queried relationships"
            panel.collapsed = False
            await pilot.pause()
            tree.refresh_relationships()
            async with asyncio.timeout(5):
                while len(tree.groups) != 5:
                    await pilot.pause(.02)
            await pilot.pause()
            assert source.reads == 1
            peer = tree.groups["inbound"].rows["thread", "peer"]
            reference = app.query_one(ReferenceTree).query_one(CommsRow)
            assert peer.render().plain == reference.render().plain
            assert peer.styles.height == reference.styles.height
            assert peer.has_class("-busy") == reference.has_class("-busy")
            assert peer.has_class("-unread") == reference.has_class("-unread")
            peer.action_open_selected()
            await pilot.pause()
            assert app.opened[-1] == ("peer", "thread")
            assert peer.has_class("-selected")
            assert tree.view_state.selected == ("inbound", "peer")
            tree.groups["inbound"].rows["channel", "#team"].action_open_selected()
            await pilot.pause()
            assert app.opened[-1] == ("#team", "channel")
            assert not peer.has_class("-selected")

            children = tree.groups["children"]
            identities = dict(children.rows)
            sort_control = panel.query_one(RelationshipSort)
            await sort_control._save_order(ThreadSort.LAST_ACTIVITY)
            await pilot.pause()
            assert sort_control.order is ThreadSort.LAST_ACTIVITY
            original = source.people["child-00"]
            source.people["child-00"] = replace(
                original, activity=replace(original.activity, timestamp=100))
            source.version += 1
            app.coordination_observed.publish(None)
            await pilot.pause()
            async with asyncio.timeout(5):
                while children.model.entries[0].target != "child-00":
                    await pilot.pause(.02)
            assert all(children.rows[key] is row for key, row in identities.items())
            assert children.member_container.max_scroll_y > 0
            children.toggle_members()
            await pilot.pause()
            assert not children.member_container.display
            children.toggle_members()
            await pilot.pause()
            assert children.member_container.display

            before = source.reads
            panel.collapsed = True
            source.version += 1
            app.coordination_observed.publish(None)
            await pilot.pause()
            assert source.reads == before
            panel.collapsed = False
            await pilot.pause()
            tree.refresh_relationships()
            await pilot.pause()
            assert source.reads > before
            # Different connection identities never reuse the last visible
            # owner's rows, even when the backend replies late or incorrectly.
            other_source = FixtureSource(Path(directory) / "other")
            tree.set_identity("other-owner", other_source.root, source=other_source)
            assert all(not group.display for group in tree.groups.values())
            await pilot.pause()
            async with asyncio.timeout(5):
                while tree._snapshot is None:
                    tree.refresh_relationships()
                    await pilot.pause(.02)
            assert tree._snapshot.owner == "other-owner"
            opened = list(app.opened)
            tree.groups["inbound"].rows["thread", "peer"].action_open_selected()
            await pilot.pause()
            assert app.opened == opened, "Foreign-root entry navigated into the original wire"
            tree.set_identity("owner", source.root, source=source)
            await pilot.pause()
            async with asyncio.timeout(5):
                while tree._snapshot is None:
                    tree.refresh_relationships()
                    await pilot.pause(.02)
            if path := os.environ.get("TOAD_RIGHT_SIDEBAR_SVG"):
                app.save_screenshot(path)
            # Exercise the same mounted widget for both parties using one real
            # core service. Neither panel invents a directional relationship.
            comms = Comms(Path(directory) / "mutual")
            for name in ("owner", "peer"):
                comms.register(Thread(name, frozenset(), directory))
            comms.relationships.edit("peer", "add", "owner", "Shared review")
            shared = WireRelationshipSource(str(comms.root), comms)
            for owner, partner in (("owner", "peer"), ("peer", "owner")):
                tree.set_identity(owner, str(comms.root), source=shared)
                async with asyncio.timeout(5):
                    while tree._snapshot is None or tree._snapshot.owner != owner:
                        tree.refresh_relationships(force=True)
                        await pilot.pause(.02)
                rows = tree.groups["collaborating"].model.entries
                assert len(rows) == 1
                assert (rows[0].target, rows[0].detail) == (partner, "Shared review")
            comms.relationships.edit("owner", "remove", "peer")
            async with asyncio.timeout(5):
                while tree.groups["collaborating"].model.entries:
                    tree.refresh_relationships(force=True)
                    await pilot.pause(.02)
            assert comms.relationships.snapshot("owner").groups[4].entries == ()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("right Comms fixture: five groups, shared rows, navigation, sort, "
          "collapse, both mutual panels, no hidden queries")


if __name__ == "__main__":
    asyncio.run(main())
