"""Textual-facing: a long sidebar list is mounted a layout step at a time, top first, a step's worth per frame by the screen's stepped layout."""

import unittest

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Static

from toad.textual_colours import ThemedApp
from toad.widgets.sidebar_tree import SidebarGroup


class Row(Static):
    pass


class Group(SidebarGroup):
    """A group whose members are numbered rows; creating each counts toward its step."""

    def __init__(self, count: int) -> None:
        self.keys = tuple(f"row-{index}" for index in range(count))
        self.members: dict[str, Row] = {}
        self.painted: list[str] = []
        super().__init__(Static("group"), expanded=True)

    def on_mount(self) -> None:
        self.sync_members()

    def sync_members(self, changed=None) -> None:
        def update(key, row):
            if changed is None or key in changed or not row.has_class("-painted"):
                row.add_class("-painted")
                self.painted.append(key)

        self.reconcile_rows(self.keys, self.members, lambda key: Row(key), update)


class Rows(ThemedApp, App):
    def __init__(self, count: int) -> None:
        super().__init__()
        self.count = count
        self.frames: list[tuple[int, bool]] = []

    def compose(self) -> ComposeResult:
        yield Static("before")

    def _display(self, screen: Screen, renderable) -> None:
        if renderable is not None:
            group = screen.query_one_optional(Group)
            self.frames.append((len(group.member_container.children) if group else -1, bool(screen._frame_holds)))
        super()._display(screen, renderable)


class SidebarRowsInSteps(unittest.IsolatedAsyncioTestCase):
    async def test_long_list_mounts_a_step_per_frame_in_order(self):
        app = Rows(400)
        async with app.run_test(size=(60, 30)) as pilot:
            app.screen.LAYOUT_STEP_NS = 1_000_000
            group = Group(app.count)
            await app.screen.mount(group)
            first = len(group.member_container.children)
            self.assertGreater(first, 0)
            self.assertLess(first, app.count, "the first step mounts only part of the list")
            await pilot.pause()
            while group._row_mounting is not None and not group._row_mounting.is_finished:
                await pilot.pause()
            await pilot.pause()
            children = list(group.member_container.children)
            self.assertEqual([str(row.render()) for row in children], list(group.keys))
            self.assertEqual(sorted(group.painted), sorted(group.keys), "each row painted once")
            # Frames are written while the list grows: each shows more rows.
            counts = [count for count, _held in app.frames if count > 0]
            self.assertGreater(len(set(counts)), 2)
            self.assertEqual(counts, sorted(counts))
            self.assertEqual(counts[-1], app.count)
            self.assertFalse(any(held for _count, held in app.frames))

    async def test_short_list_mounts_at_once(self):
        app = Rows(5)
        async with app.run_test(size=(60, 30)) as pilot:
            # "Short" means the whole list fits in one step; a step is a time budget,
            # so the budget is fixed here the way the long-list test fixes it.
            app.screen.LAYOUT_STEP_NS = 1_000_000_000
            group = Group(app.count)
            await app.screen.mount(group)
            self.assertEqual(len(group.member_container.children), app.count)
            self.assertIsNone(group._row_mounting)
            await pilot.pause()

