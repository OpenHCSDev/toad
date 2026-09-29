"""New destinations activate through the mounted row without changing a dispatcher."""

import ast
import asyncio
from pathlib import Path
import unittest

from textual.app import App, ComposeResult
from textual.screen import Screen
from toad.navigation_target import NavigationContext, NavigationOwner, NavigationTarget
from toad.widgets.comms_sidebar import CommsRow


class SidebarDestinationsTest(unittest.IsolatedAsyncioTestCase):
    async def test_new_destination_uses_existing_row(self):
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

        class DestinationApp(App):
            @property
            def selected_session(self):
                return self.screen

            def get_default_screen(self):
                return DestinationScreen()

        app = DestinationApp()
        async with app.run_test() as pilot:
            await pilot.click(CommsRow)
            await asyncio.wait_for(selected.wait(), 2)
            self.assertEqual(app.selected_destination, "report")

    def test_retired_row_dispatch_is_absent(self):
        source = Path(__file__).resolve().parents[1] / "src/toad"
        for relative in (
            "navigation_target.py", "widgets/comms_sidebar.py",
            "widgets/thread_comms.py",
        ):
            tree = ast.parse((source / relative).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "kind":
                    if isinstance(node.value, ast.Name):
                        self.assertNotIn(node.value.id, {"row", "choice"}, relative)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "NavigationTarget":
                        self.assertNotEqual(node.func.attr, "decode", relative)
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    self.assertNotEqual(node.target.id, "kind", relative)


if __name__ == "__main__":
    unittest.main()
