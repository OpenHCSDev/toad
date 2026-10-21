"""Textual-facing: while a route's metadata is read off the UI thread the prompt keeps taking keys, focus stays where the user moved it, and a superseded or orphaned opening creates no tab."""

import asyncio
import threading
from unittest.mock import patch

from toad.navigation_preparation import CommsNavigationRequest, ThreadNavigationRequest
from toad.navigation_context import NavigationContext
from toad.navigation_target import ThreadTarget, channel_target


class Gate:
    """Holds a request type's read on a worker thread until released."""

    def __init__(self, request_type):
        self.request_type = request_type
        self.entered, self.release = threading.Event(), threading.Event()
        self.thread_ids = []
        self.original = request_type.read

    def read(self, request):
        self.thread_ids.append(threading.get_ident())
        self.entered.set()
        if not self.release.wait(8):
            raise TimeoutError("route read gate was not released")
        return self.original(request)

    def holding(self):
        return patch.object(self.request_type, "read", lambda request: self.read(request))


async def opening_while_the_user_types(workspace, request_type, target):
    workspace.thread("metadata-peer", running=True)
    async with workspace.app(size=(100, 32)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        source = app.selected_session
        other = await ui.new_session()
        await ui.select_tab(owner)
        gate = Gate(request_type)
        context = NavigationContext(app, owner, workspace.project, source._comms_thread)
        opening = None
        try:
            with gate.holding():
                opening = asyncio.create_task(target.open(context))
                assert await asyncio.to_thread(gate.entered.wait, 2)
                assert gate.thread_ids == [gate.thread_ids[0]] and gate.thread_ids[0] != threading.get_ident()
                assert ui.selected_tab == owner
                await ui.write_draft("")
                await ui.type("keep")
                assert ui.draft().endswith("keep")
                await asyncio.wait_for(ui.select_tab(other), 2)
                assert not gate.release.is_set() and not opening.done()
                gate.release.set()
                assert await asyncio.wait_for(opening, 2) == other
                assert ui.selected_tab == other, "Old route metadata stole focus"
                assert len(ui.tabs()) == 2, "Superseded route created an unused tab"
                assert not app.thread_navigation.pending
        finally:
            gate.release.set()
            if opening is not None:
                await asyncio.gather(opening, return_exceptions=True)


async def test_a_thread_opening_reads_off_the_ui_thread_and_a_later_tab_choice_wins(workspace):
    await opening_while_the_user_types(workspace, ThreadNavigationRequest, ThreadTarget("metadata-peer"))


async def test_a_channel_opening_reads_off_the_ui_thread_and_a_later_tab_choice_wins(workspace):
    await opening_while_the_user_types(workspace, CommsNavigationRequest, channel_target("#all"))


async def test_a_renamed_thread_reuses_its_open_tab_before_the_rename_reaches_the_view(workspace):
    workspace.thread("metadata-peer", running=True)
    async with workspace.app(size=(100, 32)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        other = await ui.new_session()
        existing = app.session_navigation.source(other)
        existing.initial_coordination_root = str(workspace.roots.wire)
        existing._comms_thread = "metadata-peer"
        workspace.comms.registry.rename("metadata-peer", "metadata-renamed")
        reused = await app.thread_navigation.open(
            owner_mode=owner, project_path=workspace.project, target="metadata-peer")
        assert reused == other and app.session_tracker.session_count == 2


async def test_a_channel_read_finishing_after_its_owner_closed_opens_in_the_remaining_tab(workspace):
    workspace.thread("metadata-peer", running=True)
    async with workspace.app(size=(100, 32)) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        source = app.selected_session
        other = await ui.new_session()
        await ui.select_tab(owner)
        gate = Gate(CommsNavigationRequest)
        opening = None
        try:
            with gate.holding():
                opening = asyncio.create_task(channel_target("#all").open(
                    NavigationContext(app, owner, workspace.project, source._comms_thread)))
                assert await asyncio.to_thread(gate.entered.wait, 2)
                await asyncio.wait_for(ui.close_tab(owner), 2)
                gate.release.set()
                assert await asyncio.wait_for(opening, 2) == other
                assert owner not in [tab.identity for tab in ui.tabs()] and len(ui.tabs()) == 1
        finally:
            gate.release.set()
            if opening is not None:
                await asyncio.gather(opening, return_exceptions=True)
