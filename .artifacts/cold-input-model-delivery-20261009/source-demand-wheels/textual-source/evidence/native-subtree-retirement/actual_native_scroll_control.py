"""Locate existing native cache misses during actual PageDown dispatch."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from textual.app import App, ComposeResult
from textual.containers import VerticalGroup, VerticalScroll
from textual.widgets import Static
from textual._compositor import Compositor, IntrinsicSubtreeGeometry


class NativeBody(VerticalGroup):
    CACHE_SUBTREE_GEOMETRY = True


class NativeReader(VerticalScroll):
    CACHE_SUBTREE_GEOMETRY = True


class NativeScrollApp(App):
    CSS = """
    VerticalScroll {height: 20;}
    NativeBody {height: auto;}
    Static {height: 10;}
    #nested {height: 15; padding: 1;}
    #nested Static {height: 30;}
    #pinned {dock: top; height: 1;}
    #screen-body {height: 20;}
    #screen-placed {constrain: inside inside;}
    #overlay-body {height: 20;}
    #overlay-label {overlay: screen;}
    """

    def compose(self) -> ComposeResult:
        with NativeReader(id="reader"):
            with NativeBody(id="body"):
                for index in range(3):
                    yield Static(f"original leading {index}")
                with NativeReader(id="nested"):
                    yield Static("fixed native header", id="pinned")
                    for index in range(3):
                        yield Static("\n".join(f"nested {index} original {i}" for i in range(30)))
                for index in range(3):
                    yield Static(f"original trailing {index}")
            with NativeBody(id="screen-body"):
                yield Static("screen-constrained original", id="screen-placed")
            with NativeBody(id="overlay-body"):
                yield Static("overlay native original", id="overlay-label")


async def run(output):
    app = NativeScrollApp()
    receipt = {"scope": "Actual native scroll/reprojection counter; no installed Toad/CPU readiness claim"}
    async with app.run_test(size=(80, 30)) as pilot:
        reader = app.query_one("#reader")
        reader.focus()
        await pilot.pause()
        compositor = app.screen._compositor
        body = app.query_one("#body")
        compositor.reflow_visible(app.screen, app.screen.size)
        original = compositor._subtree_geometry[body]
        unchanged, _ = compositor._arrange_root(app.screen, app.screen.size)
        assert unchanged[body] is original.geometry[body].geometry
        receipt["original_pose_native_geometry_identity_retained"] = True
        before = (body._geometry_revision, body._nodes._updates, body.styles._cache_key)
        start = reader.scroll_y
        arrangements = 0
        arrangement_callers = []
        layout_calls = 0

        def observe(frame, event, argument):
            nonlocal arrangements, layout_calls
            if event == "call" and frame.f_code.co_name == "arrange" and frame.f_locals.get("self") is body:
                arrangements += 1
                arrangement_callers.append(frame.f_back.f_code.co_name)
            if (event == "call" and frame.f_code.co_name == "arrange"
                    and frame.f_globals.get("__name__") == "textual._arrange"
                    and frame.f_locals.get("widget") is body):
                layout_calls += 1

        sys.setprofile(observe)
        try:
            await pilot.press("pagedown")
            await pilot.pause()
            compositor.reflow_visible(app.screen, app.screen.size)
        finally:
            sys.setprofile(None)
        current = compositor._subtree_geometry[body]
        receipt.update(scroll_before=start, scroll_after=reader.scroll_y,
            same_resource=current is original, body_arrangement_calls_during_pagedown=arrangements,
            native_body_epoch_unchanged=before == (body._geometry_revision, body._nodes._updates, body.styles._cache_key),
            changed_key_positions=[index for index, (old, new) in enumerate(zip(original.key, current.key)) if old != new],
            changed_key_values=[{"index": index, "before": repr(old), "after": repr(new)}
                for index, (old, new) in enumerate(zip(original.key, current.key)) if old != new])
        assert reader.scroll_y > start, "Actual PageDown was not admitted"
        assert receipt["native_body_epoch_unchanged"], receipt
        assert current is original, "Original intrinsic resource was rebuilt during PageDown"
        assert isinstance(current, IntrinsicSubtreeGeometry)
        assert not arrangements, "The same native body was recursively arranged during PageDown"
        assert not isinstance(compositor._subtree_geometry[reader], IntrinsicSubtreeGeometry)

        def visible_scene(mapping):
            return {node: entry for node, entry in mapping.items()
                    if app.screen.size.region.overlaps(entry.region)
                    and entry.clip.overlaps(entry.region)}

        def check_scene(label):
            cached, _ = compositor._arrange_root(app.screen, app.screen.size)
            reference, _ = Compositor(max_subtree_geometry_entries=0)._arrange_root(
                app.screen, app.screen.size, visible_only=False)
            projected, expected = visible_scene(cached), visible_scene(reference)
            assert projected == expected, (label, [
                (type(node).__name__, node.id, projected.get(node), expected.get(node))
                for node in projected.keys() | expected.keys()
                if projected.get(node) != expected.get(node)])
            receipt.setdefault("scene_checks", []).append(label)

        check_scene("PageDown reveals previously clipped descendants")

        async def check_placement(label, operation):
            nonlocal arrangements, layout_calls
            arrangements = 0
            layout_calls = 0
            arrangement_callers.clear()
            sys.setprofile(observe)
            try:
                await operation()
                await pilot.pause()
                compositor.reflow_visible(app.screen, app.screen.size)
            finally:
                sys.setprofile(None)
            assert compositor._subtree_geometry[body] is original, label
            assert not layout_calls, (label, layout_calls, arrangement_callers)
            assert "arrange_widget" not in arrangement_callers, (label, arrangement_callers)
            check_scene(label)
            receipt.setdefault("placement_checks", []).append({
                "label": label, "same_resource": True, "body_arrangement_calls": arrangements,
                "body_layout_executions": layout_calls, "arrangement_callers": arrangement_callers.copy(),
                "current_geometry": repr(compositor._visible_map[body]),
            })

        prefix = Static("new original native sibling", id="prefix")

        async def prepend():
            await reader.mount(prefix, before=body)

        async def reorder():
            reader.move_child(prefix, after=body)

        async def retire():
            await prefix.remove()

        async def relocate():
            reader.styles.offset = (3, 1)

        async def return_host():
            reader.styles.offset = (0, 0)

        await check_placement("Prepend changes root virtual placement", prepend)
        await check_placement("Sibling reorder changes native descendant paint rank", reorder)
        await check_placement("Sibling retirement preserves unrelated resource", retire)
        await check_placement("Host placement projects nested clip and root coordinates", relocate)
        await check_placement("Returning host retains original native arrangement", return_host)
        await pilot.press("pageup")
        await pilot.pause()
        check_scene("Reverse restores nested clip")
        assert compositor._subtree_geometry[body] is original
        nested = app.query_one("#nested")
        await pilot.press("pagedown")
        await pilot.pause()
        compositor._arrange_root(app.screen, app.screen.size, retain_geometry=(body,))
        culled = compositor._subtree_geometry[nested]
        assert culled.key.visible_only, "Targeted outer traversal did not cull the nested viewport"
        compositor.discard_widgets({body})
        compositor._arrange_root(app.screen, app.screen.size)
        complete = compositor._subtree_geometry[nested]
        assert not complete.key.visible_only, "Complete ancestor reused culled descendant coverage"
        assert complete is not culled, "Two different native coverage requests aliased one resource"
        assert len(complete.geometry) > len(culled.geometry)
        receipt["complete_culled_native_coverage_distinct"] = True
        check_scene("Culled to complete descendant resource transition")
        nested.focus()
        await pilot.press("end")
        await pilot.pause()
        check_scene("Nested native scrolling and fixed child")
        reader.focus()
        await pilot.press("end")
        await pilot.pause()
        check_scene("End clips final descendants")
        for _ in range(3):
            await pilot.press("pagedown")
        await pilot.pause()
        check_scene("Repeated PageDown at bottom")
        await pilot.resize_terminal(70, 25)
        await pilot.pause()
        check_scene("Resize invalidates intrinsic dimensions")
        assert compositor._subtree_geometry[body] is not original
        retained = compositor._subtree_geometry[body]
        body.query_one(Static).update("original content changed\nnew line")
        await pilot.pause()
        check_scene("Native content mutation invalidates resource")
        assert compositor._subtree_geometry[body] is not retained
        constrained = app.query_one("#screen-body")
        check_scene("Screen-dependent placement retains original coordinates")
        assert not isinstance(compositor._subtree_geometry[constrained], IntrinsicSubtreeGeometry)
        overlay = app.query_one("#overlay-body")
        check_scene("Overlay uses canonical screen clip and paint order")
        assert not isinstance(compositor._subtree_geometry[overlay], IntrinsicSubtreeGeometry)
        receipt["result"] = "PASS"
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    asyncio.run(run(Path(sys.argv[1])))
