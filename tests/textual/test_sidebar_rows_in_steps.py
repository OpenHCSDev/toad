"""Textual-facing: a long sidebar list is mounted a layout step at a time, top first, a step's worth per frame by the screen's stepped layout."""
from functools import cached_property
from pathlib import Path

import asyncio
from unittest.mock import patch

from textual.screen import Screen
from textual.widgets import Static

from toad.app import ToadApp
from toad.tone_paint import AlternatingTone
from toad.widgets.sidebar_tree import SidebarGroup, TargetTree


class Row(AlternatingTone, Static):
    pass


class Group(SidebarGroup):
    """A group whose members are numbered rows; creating each counts toward its step."""

    def __init__(self, count: int) -> None:
        self.keys = tuple(f"row-{index}" for index in range(count))
        self.painted: list[str] = []
        super().__init__(Static("group"), expanded=True)

    @property
    def member_keys(self) -> tuple[str, ...]:
        return self.keys

    def new_row(self, key: str) -> Row:
        return Row(key)

    def show_member(self, key: str, row: Row) -> None:
        row.add_class("-painted")
        self.painted.append(key)

    def sync_members(self, changed: frozenset[str]) -> None:
        self.reconcile_rows(changed=changed)


class Tree(TargetTree):
    """A tree that only builds rows: it opens no menus and navigates from a fixed root."""

    @property
    def navigation_groups(self):
        return self.query(Group)

    def show_row_menu(self, row, offset) -> None:
        """This fixture never opens a row menu."""

    @property
    def navigation_root(self) -> Path:
        return Path(".")


class Rows(ToadApp):
    @cached_property
    def frames(self) -> list[tuple[int, bool]]:
        return []

    def _display(self, screen: Screen, renderable) -> None:
        if renderable is not None:
            group = screen.query_one_optional(Group)
            self.frames.append((len(group.member_container.children) if group else -1, bool(screen._frame_holds)))
        super()._display(screen, renderable)


class TestSidebarRowsInSteps:
    async def test_reconciliation_mounts_one_cohort_and_keeps_native_rows(self, workspace):
        async with workspace.app(application=Rows, session=False, size=(60, 30)) as ui:
            app, pilot = ui.textual
            tree = Tree()
            await app.screen.mount(tree)
            app.screen.LAYOUT_STEP_NS = 1_000_000_000
            group = Group(0)
            await tree.mount(group)
            await pilot.pause()
            group.keys = tuple(f"row-{index}" for index in range(40))
            with patch.object(group.member_container, "mount", wraps=group.member_container.mount) as mount:
                group.sync_members(frozenset())
                assert mount.call_count == 1
            await pilot.pause()
            original = dict(group.rows)
            assert list(group.member_container.children) == [original[key] for key in group.keys]
            painted = len(group.painted)
            group.keys = ("new-first", *reversed(group.keys[15:]), "new-last")
            with patch.object(group.member_container, "mount", wraps=group.member_container.mount) as mount:
                group.sync_members(frozenset({"row-24"}))
                assert mount.call_count == 1
            await pilot.pause()
            assert list(group.member_container.children) == [group.rows[key] for key in group.keys]
            assert all(group.rows[key] is original[key] for key in group.keys if key in original)
            assert all(not row.is_attached for key, row in original.items() if key not in group.keys)
            assert group.painted[painted:] == ["new-first", "row-24", "new-last"]
            painted = len(group.painted)
            with patch.object(group.member_container, "mount", wraps=group.member_container.mount) as mount:
                group.sync_members(frozenset())
                assert mount.call_count == 0
            assert len(group.painted) == painted

    async def test_long_list_mounts_a_step_per_frame_in_order(self, workspace):
        count = 400
        async with workspace.app(application=Rows, session=False, size=(60, 30)) as ui:
            app, pilot = ui.textual
            tree = Tree()
            await app.screen.mount(tree)
            app.screen.LAYOUT_STEP_NS = 1_000_000
            group = Group(count)
            await tree.mount(group)
            first = len(group.member_container.children)
            assert first > 0
            assert first < count, "the first step mounts only part of the list"
            await pilot.pause()
            # Every step mounts at least one row, so 400 rows finish in at most 400 steps.
            async with asyncio.timeout(30):
                while not group._row_mounting.is_finished:
                    await pilot.pause()
            await pilot.pause()
            children = list(group.member_container.children)
            assert [str(row.render()) for row in children] == list(group.keys)
            assert sorted(group.painted) == sorted(group.keys), "each row painted once"
            # Frames are written while the list grows: each shows more rows.
            counts = [count for count, _held in app.frames if count > 0]
            assert len(set(counts)) > 2
            assert counts == sorted(counts)
            assert counts[-1] == count
            assert not (any(held for _count, held in app.frames))

    async def test_short_list_mounts_at_once(self, workspace):
        count = 5
        async with workspace.app(application=Rows, session=False, size=(60, 30)) as ui:
            app, pilot = ui.textual
            tree = Tree()
            await app.screen.mount(tree)
            # "Short" means the whole list fits in one step; a step is a time budget,
            # so the budget is fixed here the way the long-list test fixes it.
            app.screen.LAYOUT_STEP_NS = 1_000_000_000
            group = Group(count)
            unscheduled = group._row_mounting
            assert unscheduled.is_finished
            assert not (unscheduled.is_running)
            await tree.mount(group)
            assert len(group.member_container.children) == count
            assert group._row_mounting is unscheduled
            await pilot.pause()

