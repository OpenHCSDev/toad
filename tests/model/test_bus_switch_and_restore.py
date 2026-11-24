"""Concurrency and teardown guarantees for bus switching and saved-tab restoration."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from toad.application_lifetime import ApplicationLifetime
from toad.client.connection import CoordinationAccess
from toad.client.tab_identity import TabNotDrawnHere, TabTargetGone
from toad.session_navigation import Detached, SessionNavigation


@dataclass(frozen=True)
class _FakeTab:
    mode_name: str
    action: object

    async def entry(self, navigation):
        return await self.action(self, navigation)


@pytest.mark.asyncio
async def test_restored_tabs_prepares_entries_concurrently_in_saved_order() -> None:
    barrier = asyncio.Barrier(3)
    registered: list[str] = []
    opened: list[str] = []
    closed_batches: list[tuple[object, ...]] = []
    errors: list[str] = []

    async def ok_entry(tab: _FakeTab, _nav):
        await barrier.wait()
        return f"entry:{tab.mode_name}"

    async def gone_entry(tab: _FakeTab, _nav):
        raise TabTargetGone(tab, "gone")

    async def undrawn_entry(tab: _FakeTab, _nav):
        raise TabNotDrawnHere(tab)

    tabs = (
        _FakeTab("t1", ok_entry),
        _FakeTab("stale-1", gone_entry),
        _FakeTab("t2", ok_entry),
        _FakeTab("undrawn", undrawn_entry),
        _FakeTab("stale-2", gone_entry),
        _FakeTab("t3", ok_entry),
    )

    class _FakeNav:
        def get(self, _mode):
            return None

        async def register(self, entry):
            registered.append(entry)

        async def open(self, entry):
            opened.append(entry)

    class _FakeOrder:
        async def load(self):
            return tabs

        async def close(self, modes):
            closed_batches.append(tuple(modes))

    app = SimpleNamespace(
        session_navigation=_FakeNav(),
        tab_order=_FakeOrder(),
        log_error=errors.append,
    )
    lifetime = ApplicationLifetime(app, resumed_session=None)  # type: ignore[arg-type]

    open_last = await asyncio.wait_for(lifetime.restored_tabs(), timeout=2.0)
    await open_last()

    assert registered == ["entry:t1", "entry:t2", "entry:t3"]
    assert opened == ["entry:t3"]
    assert closed_batches == [(tabs[1], tabs[4])]
    assert len(errors) == 2


@pytest.mark.asyncio
async def test_switch_connection_does_not_block_on_previous_connection_close() -> None:
    release_close = threading.Event()
    close_started = threading.Event()
    close_finished = threading.Event()

    class _SlowConnection:
        def close(self) -> None:
            close_started.set()
            release_close.wait(timeout=5.0)
            close_finished.set()

    class _NewConnection:
        def close(self) -> None:
            pass

    access = object.__new__(CoordinationAccess)
    access.connection = _SlowConnection()
    access.route_task = None
    access.retiring = set()
    access.retry = SimpleNamespace(recovered=lambda: None)

    async def fake_observe_route() -> None:
        return None

    access.observe_route = fake_observe_route  # type: ignore[method-assign]

    await asyncio.wait_for(access.switch_connection(_NewConnection()), timeout=1.0)
    assert isinstance(access.connection, _NewConnection)
    assert len(access.retiring) == 1
    assert not close_finished.is_set()

    release_close.set()
    await asyncio.gather(*tuple(access.retiring))
    assert close_started.is_set()
    assert close_finished.is_set()
    assert access.retiring == set()


@pytest.mark.asyncio
async def test_finish_views_closes_detached_views_concurrently() -> None:
    barrier = asyncio.Barrier(2)
    finished: list[str] = []

    class _FakeWorkspaceSessions:
        async def finish(self, view: str) -> None:
            await barrier.wait()
            finished.append(view)

    nav = object.__new__(SessionNavigation)
    nav.app = SimpleNamespace(workspace_sessions=_FakeWorkspaceSessions())

    await asyncio.wait_for(
        nav.finish_views(Detached((), ("v1", "v2"), None, None)),  # type: ignore[arg-type]
        timeout=2.0,
    )
    assert set(finished) == {"v1", "v2"}
