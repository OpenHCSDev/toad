"""The view settings bar exposes the viewed object's right-click options through one shared owner."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from toad.client.menu_entry import MenuEntry
from toad.client.sidebar_panels import ViewActionsPanel
from toad.client.view_settings import ViewSettingsOwner
from toad.command_catalog import CommandCatalog
from toad.qt.menu import QtMenuRow
from toad.qt.placement import QtViewActions
from toad.qt.theme import offered_schemes


class _FakeView(ViewSettingsOwner):
    def __init__(self, *, mode: str, contexts: tuple, tab_entries: tuple[MenuEntry, ...]) -> None:
        self._mode = mode
        self._contexts = contexts
        self.navigation_target = SimpleNamespace(configuration_contexts=lambda _view: self._contexts)

        async def _run_thread(fn, *args):
            return fn(*args)

        self.app = SimpleNamespace(
            preparation=SimpleNamespace(run_thread=_run_thread),
            session_navigation=SimpleNamespace(tab_menu=lambda m: tab_entries if m == mode else ()),
        )

    @property
    def configuration_mode(self) -> str:
        return self._mode


@pytest.mark.asyncio
async def test_view_menu_entries_uses_pointer_menu_for_subject_and_tab_menu_for_file(monkeypatch) -> None:
    ran: list[str] = []
    pointer_entries = (
        MenuEntry("Pin", lambda: ran.append("pin")),
        MenuEntry("Copy name", lambda: ran.append("copy")),
    )
    tab_entries = (
        MenuEntry("Move left", lambda: ran.append("left")),
        MenuEntry("Close tab", lambda: ran.append("close")),
    )

    async def fake_pointer_menu(ctx):
        assert ctx == "channel-context"
        return pointer_entries

    monkeypatch.setattr(CommandCatalog, "pointer_menu", classmethod(lambda cls, ctx: fake_pointer_menu(ctx)))

    # Channel / thread view: delegates to CommandCatalog.pointer_menu(context).
    channel_view = _FakeView(mode="comms-1", contexts=("channel-context",), tab_entries=tab_entries)
    assert await channel_view.view_menu_entries() == pointer_entries

    # File view (no configuration_contexts): falls back to SessionNavigation.tab_menu(mode).
    file_view = _FakeView(mode="file-1", contexts=(), tab_entries=tab_entries)
    assert await file_view.view_menu_entries() == tab_entries


@pytest.mark.asyncio
async def test_qt_view_actions_renders_declared_menu_entries_with_qt_menu_rows(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    qapp = QApplication.instance() or QApplication([])

    ran: list[str] = []
    entries = (
        MenuEntry("Pin", lambda: ran.append("pin")),
        MenuEntry("Archive", lambda: ran.append("archive")),
    )

    async def _entries():
        return entries

    view = SimpleNamespace(view_menu_entries=_entries, app=SimpleNamespace(show_error=lambda *a: None))
    scheme = next(iter(offered_schemes(os.environ).values()))

    class _Renderer:
        def themed(self, _widget, apply_fn) -> None:
            apply_fn()

        def theme(self, colour_type) -> str:
            return colour_type.rgb(scheme).hex

    panel = QtViewActions(view, _Renderer())
    assert isinstance(panel, ViewActionsPanel)

    await panel.refresh_entries()
    rows = panel.findChildren(QtMenuRow)
    assert [row.label.text() for row in rows] == ["Pin", "Archive"]

    rows[0]._button.click()
    rows[1]._button.click()
    assert ran == ["pin", "archive"]

    panel.release_page()
    qapp.processEvents()
