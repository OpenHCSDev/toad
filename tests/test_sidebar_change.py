"""The declared change touches only the native rows it names."""

from contextlib import contextmanager
from types import SimpleNamespace
import unittest

from toad.widgets.sidebar_tree import AllSidebarRows, ChangedChannels, ChangedThreads


class Group:
    def __init__(self, names):
        self.rows = dict.fromkeys(names)
        self.painted = []
        self.reconciled = 0
        self.presented = 0

    def repaint_members(self, names):
        self.painted.extend(name for name in names if name in self.rows)

    def present(self, channel):
        self.presented += 1

    def sync_members(self):
        self.reconciled += 1


class Sidebar:
    def __init__(self):
        self.groups = {"#one": Group(("alice", "bob")), "#two": Group(("carol",))}
        self.reconciliation_count = 0
        self.open_views = {}

    @contextmanager
    def reconcile_members(self):
        self.reconciliation_count += 1
        yield

    def find_open_views(self):
        return {"alice": "tab"}


class SidebarChangeTest(unittest.TestCase):
    def test_one_thread_paints_one_row_without_reconciling_other_members(self):
        sidebar = Sidebar()
        ChangedThreads(frozenset(("bob",))).apply_comms(sidebar, {})
        self.assertEqual([group.painted for group in sidebar.groups.values()], [["bob"], []])
        self.assertEqual([group.reconciled for group in sidebar.groups.values()], [0, 0])
        self.assertEqual(sidebar.reconciliation_count, 0)

    def test_channel_and_whole_model_reconcile_only_their_own_scope(self):
        sidebar = Sidebar()
        rows = {key: SimpleNamespace() for key in sidebar.groups}
        ChangedChannels(frozenset(("#one",))).apply_comms(sidebar, rows)
        self.assertEqual([group.reconciled for group in sidebar.groups.values()], [1, 0])
        AllSidebarRows().apply_comms(sidebar, rows)
        self.assertEqual([group.reconciled for group in sidebar.groups.values()], [2, 1])
        self.assertEqual(sidebar.open_views, {"alice": "tab"})
