"""One native project panel journey; no wire, sessions or native agent."""
import asyncio
from pathlib import Path

from textual import on
from textual.app import App
from textual.geometry import Offset
from textual.widgets import Tree
from textual.worker import WorkerCancelled

from toad.widgets.project_panel import RestorableProjectPanel
from toad.widgets.project_tree_intent import ProjectTreeIntent
from toad.widgets.session_thread_panels import ProjectSessionPanel


def test_retirement_during_restore_keeps_the_project_reader(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    for index in range(40):
        (project / f"file{index:02}.txt").write_text(f"Authored file {index}\n")
    selected = project / "file30.txt"
    intended = ProjectTreeIntent(project, frozenset({project}), selected, Offset(0, 25))
    owner = ProjectSessionPanel()
    owner.intent = intended

    async def journey():
        retired = asyncio.Event()
        captured = []
        panel = RestorableProjectPanel(project, intent=owner.intent)

        class ProjectApp(App):
            def compose(self):
                yield panel

            def on_mount(self):
                self.mount_worker = panel._mount_tree()

            @on(Tree.NodeHighlighted)
            async def initial_root(self, event):
                if (event.control is panel.directory_tree
                        and event.node is panel.directory_tree.root
                        and not retired.is_set()):
                    # The original native initialization highlight is not a
                    # completed filesystem reader. Retire at this actual event,
                    # using the same declaration capture as SessionThreadSidebar.
                    owner.capture(panel)
                    captured.append(owner.intent)
                    await panel.remove()
                    retired.set()

        app = ProjectApp()
        async with app.run_test(size=(60, 10)) as pilot:
            await retired.wait()
            assert captured == [intended]
            assert not panel.is_attached
            try:
                await app.mount_worker.wait()
            except WorkerCancelled:
                pass
            assert app.mount_worker.is_finished

            restored = RestorableProjectPanel(project, intent=owner.intent)
            await app.mount(restored)
            await restored._mount_tree().wait()
            tree = restored.directory_tree
            assert tree.cursor_node.data.path == selected
            assert tree.scroll_offset == intended.scroll
            owner.capture(restored)
            assert owner.intent.selected == selected
            assert owner.intent.scroll == intended.scroll
            assert project in owner.intent.expanded
            assert owner.intent == restored.capture_intent()
            await restored.remove()
            await pilot.pause()
            assert not restored.is_attached
        assert app._exception is None

    asyncio.run(journey())
