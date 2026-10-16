"""Textual-facing: a navigation destination declared as a target class is opened by the mounted sidebar row without a dispatcher."""

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.screen import Screen

from toad.navigation_target import NavigationContext, NavigationOwner, NavigationTarget
from toad.textual_colours import ThemedApp
from toad.widgets.comms_sidebar import CommsRow


async def test_new_destination_uses_existing_row():
    selected = asyncio.Event()

    class TestReportTarget(NavigationTarget):
        async def open(self, context):
            context.app.selected_destination = self.name
            selected.set()
            return context.app.current_mode

    class DestinationScreen(NavigationOwner, Screen):
        @property
        def navigation_context(self):
            return NavigationContext(self.app, self.app.current_mode, Path.cwd(), "viewer")

        def compose(self) -> ComposeResult:
            yield CommsRow(TestReportTarget("report"), "Open report")

    class DestinationApp(ThemedApp, App):
        @property
        def selected_session(self):
            return self.screen

        def get_default_screen(self):
            return DestinationScreen()

    app = DestinationApp()
    async with app.run_test() as pilot:
        await pilot.click(CommsRow)
        await asyncio.wait_for(selected.wait(), 2)
        assert app.selected_destination == "report"
