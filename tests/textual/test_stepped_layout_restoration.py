"""Textual-facing: a tab switch's layout runs over loop turns in the compositor; history work between its steps stays correct.

- A history change that requests a layout while a stepped layout is paused
  waits for the layout that places its change, not the one already running.
- Until the step that commits the arrangement, the history window's row reads
  (_layout_map) are the previous scene's; published geometry (_published_map, hit
  testing) stays the previous scene's until the last step.
- The stepped layout's scene equals a one-shot layout of the same change.
"""

from textual import messages
from textual._compositor import StepDeadline
from toad.widgets.agent_response import AgentResponse
from toad.widgets.history_anchor import BlockPosition, HistoryChange


def drive(screen):
    steps = screen._stepped_layout = screen._layout_steps(deadline=StepDeadline())
    next(steps)
    return steps


def scene(screen):
    return sorted(((type(widget).__name__, widget.id, geometry.region, geometry.virtual_region)
                   for widget, geometry in screen._compositor._layout_map.items()), key=repr)


async def widen(ui, screen, width):
    """A content-width change recorded as one pending layout request."""
    view = ui.conversation
    view.styles.width = width
    await screen._on_layout(messages.Layout(view))


async def test_stepped_layout_keeps_previous_scene_and_restoration_waits_for_the_next_layout(workspace):
    async with workspace.app(size=(139, 30)) as ui:
        screen = ui.app.screen
        view = ui.conversation
        await view.post(AgentResponse("\n\n".join(f"Paragraph {i} " + "word " * (i % 13) for i in range(60))))
        window = view.window
        window.anchor()
        await ui.step()
        compositor = screen._compositor

        # The sidebars mount their rows over several frames; compare scenes only once that is over.
        seen = []

        async def settled():
            await ui.step(0.1)
            seen.append(scene(screen))
            return (not ui.app.workspace_chrome.switch_toast.display
                    and len(seen) > 2 and seen[-1] == seen[-2] == seen[-3])

        await ui.until(settled, why="the workspace's widgets to finish mounting")

        # One-shot reference for the same change.
        await widen(ui, screen, 100)
        with screen.hold_frames():
            screen._refresh_layout()
        one_shot = scene(screen)
        await widen(ui, screen, "1fr")
        await ui.step()

        # Stepped, with readers and a restoration request between steps.
        restoration = HistoryChange()
        window.history_change = restoration
        restoration.request_layout(window)
        await widen(ui, screen, 100)
        layout_map, published = compositor._layout_map, compositor._published_map
        region = window.region
        hit = screen.get_widget_and_offset_at(region.x + 2, region.y + 2)
        placed = [child for child in window.walk_children() if child in layout_map]
        offsets = [row for _, row in window.placements(placed)]
        position = BlockPosition.of(window)
        assert placed and position is not None and position.bodies(window)
        with screen.hold_frames():
            steps = drive(screen)
            restoration.request_layout(window)  # made while the layout is paused
            pauses = 0
            committed = None
            try:
                while True:
                    # Textual's contract: readers see the previous arrangement until the step that
                    # commits it; later steps render, and nothing is published until the last step.
                    if committed is None and compositor._layout_map is not layout_map:
                        committed = compositor._layout_map
                    assert compositor._published_map is published, pauses
                    assert window.published_content_region == published[window].content_region.intersection(
                        published[window].clip)
                    assert screen.get_widget_and_offset_at(region.x + 2, region.y + 2) == hit
                    if committed is None:
                        assert [row for _, row in window.placements(placed)] == offsets
                        assert BlockPosition.of(window) == position
                    else:
                        assert compositor._layout_map is committed, "the arrangement changed again after its commit"
                    pauses += 1
                    next(steps)
            except StopIteration:
                screen._stepped_layout = None
        # The arrangement may commit in the last step itself, where it is published at once.
        assert compositor._layout_map is not layout_map, "the stepped layout never committed"
        assert pauses > 10, pauses
        assert scene(screen) == one_shot
        assert not restoration.layout_ready.is_set(), "released by a layout that started before its request"
        await ui.until(restoration.layout_ready.is_set, why="the next layout to answer the request")
        window.history_change = None
