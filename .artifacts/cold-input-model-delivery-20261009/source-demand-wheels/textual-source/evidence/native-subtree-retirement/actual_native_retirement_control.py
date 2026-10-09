"""Actual native mount/remove/reflow: retire one branch, retain another scene."""
import argparse
import asyncio
import json
from pathlib import Path
import sys


async def run(output):
    import textual
    from textual._compositor import Compositor
    from textual.app import App, ComposeResult
    from textual.containers import VerticalGroup
    from textual.widgets import Static

    class RetainedBody(VerticalGroup):
        CACHE_SUBTREE_GEOMETRY = True

    class NativeApp(App):
        CSS = "RetainedBody {height: 10;} Static {height: 2;}"

        def compose(self) -> ComposeResult:
            with RetainedBody(id="retiring-branch"):
                yield Static("RETIRE ME", id="retired")
                yield Static("FIRST BRANCH")
            with RetainedBody(id="retained-branch"):
                yield Static("SIBLING LIVE")

    receipt = {"textual": textual.__file__, "scope": "Actual native scene/resource control; not installed Toad readiness"}
    app = NativeApp()
    try:
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            compositor = app.screen._compositor
            retiring = app.query_one("#retiring-branch")
            retained = app.query_one("#retained-branch")
            compositor.reflow(app.screen, app.screen.size)
            original = compositor._subtree_geometry[retained]
            affected = compositor._subtree_geometry[retiring]
            retired = app.query_one("#retired")
            await retired.remove()
            receipt["unrelated_entry_retained_before_reflow"] = compositor._subtree_geometry.get(retained) is original
            receipt["affected_entry_evicted_before_reflow"] = compositor._subtree_geometry.get(retiring) is not affected
            await pilot.pause()
            compositor.reflow(app.screen, app.screen.size)
            receipt["unrelated_entry_retained_after_reflow"] = compositor._subtree_geometry[retained] is original
            frame = "\n".join(strip.text for strip in compositor.render_strips())
            receipt["visible_retained_body"] = "SIBLING LIVE" in frame
            receipt["retired_body_absent_from_frame"] = "RETIRE ME" not in frame
            receipt["no_retired_scene_custody"] = all(not entry.references_retired(owner, {retired})
                for owner, entry in compositor._subtree_geometry.items())
            scene = compositor._arrange_root(app.screen, app.screen.size)
            reference = Compositor(max_subtree_geometry_entries=0)._arrange_root(app.screen, app.screen.size)
            receipt["restored_scene_matches_uncached"] = scene == reference
            label = retained.query_one(Static)
            label.update("SIBLING LIVE\nUPDATED CONTENT")
            await pilot.pause()
            updated = compositor._arrange_root(app.screen, app.screen.size)
            receipt["content_change_invalidates_entry"] = compositor._subtree_geometry[retained] is not original
            reference = Compositor(max_subtree_geometry_entries=0)._arrange_root(app.screen, app.screen.size)
            receipt["updated_scene_matches_uncached"] = updated == reference
            compositor.max_subtree_geometry_entries = 0
            receipt["capacity_zero_retires_resources"] = not compositor._subtree_geometry
            assert all(receipt[name] for name in (
                "unrelated_entry_retained_before_reflow", "affected_entry_evicted_before_reflow",
                "unrelated_entry_retained_after_reflow", "visible_retained_body",
                "retired_body_absent_from_frame", "no_retired_scene_custody",
                "restored_scene_matches_uncached", "content_change_invalidates_entry",
                "updated_scene_matches_uncached", "capacity_zero_retires_resources")), receipt
            receipt["result"] = "PASS"
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.source_root:
        sys.path.insert(0, str(args.source_root / "src"))
    asyncio.run(run(args.output))
