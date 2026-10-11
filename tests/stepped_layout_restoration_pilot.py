"""A tab switch's layout runs over loop turns; history work between its steps stays correct.

- A history restoration that requests a layout while a stepped layout is paused
  waits for the layout that places its change, not the one already running.
- Between steps the history window's anchor reads (_layout_map) and published
  geometry (_published_map, hit testing) are the previous scene's.
- The stepped layout's scene equals a one-shot layout of the same change.
"""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import Comms
from textual import messages
from textual._compositor import StepDeadline
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.history_anchor import HistoryAnchor, WindowRestoration


def drive(screen):
    steps = screen._stepped_layout = screen._layout_steps(deadline=StepDeadline())
    next(steps)
    return steps


def finish(screen, steps) -> int:
    count = 0
    try:
        while True:
            next(steps)
            count += 1
    except StopIteration:
        screen._stepped_layout = None
    return count


def scene(screen):
    return sorted(((type(widget).__name__, widget.id, geometry.region, geometry.virtual_region)
                   for widget, geometry in screen._compositor._layout_map.items()), key=repr)


async def widen(app, pilot, screen, width):
    """A content-width change recorded as one pending layout request."""
    view = app.selected_session.conversation
    view.styles.width = width
    await screen._on_layout(messages.Layout(view))


async def main():
    with TemporaryDirectory(dir='.artifacts', prefix='stepped-layout-') as folder:
        root = Path(folder).resolve()
        os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'), XDG_STATE_HOME=str(root/'state'),
                          XDG_CONFIG_HOME=str(root/'config'), XDG_DATA_HOME=str(root/'data'))
        Comms(root/'wire').messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(139, 30)) as pilot:
            await app.selected_session.wait_content_ready()
            await pilot.pause()
            screen = app.screen
            view = app.selected_session.conversation
            await view.post(AgentResponse('\n\n'.join(f'Paragraph {i} ' + 'word ' * (i % 13) for i in range(60))))
            window = view.window
            window.anchor()
            await pilot.pause()
            compositor = screen._compositor

            # One-shot reference for the same change.
            await widen(app, pilot, screen, 100)
            with screen.hold_frames():
                screen._refresh_layout()
            one_shot = scene(screen)
            await widen(app, pilot, screen, '1fr')
            await pilot.pause()

            # Stepped, with readers and a restoration request between steps.
            restoration = WindowRestoration(None)
            window.history_restoration = restoration
            restoration.request_layout(window)
            await widen(app, pilot, screen, 100)
            layout_map, published = compositor._layout_map, compositor._published_map
            region = window.region
            hit = screen.get_widget_and_offset_at(region.x + 2, region.y + 2)
            placed = [child for child in window.walk_children() if child in layout_map]
            offsets = [HistoryAnchor._placed_offset(child, window) for child in placed]
            anchor = window.reader_anchor()
            assert placed and anchor is not None
            with screen.hold_frames():
                steps = drive(screen)
                restoration.request_layout(window)  # made while the layout is paused
                pauses = 0
                try:
                    while True:
                        assert compositor._layout_map is layout_map and compositor._published_map is published
                        assert window.published_content_region == published[window].content_region.intersection(
                            published[window].clip)
                        assert [HistoryAnchor._placed_offset(child, window) for child in placed] == offsets
                        assert window.reader_anchor() is anchor
                        assert screen.get_widget_and_offset_at(region.x + 2, region.y + 2) == hit
                        pauses += 1
                        next(steps)
                except StopIteration:
                    screen._stepped_layout = None
            assert pauses > 10, pauses
            assert scene(screen) == one_shot
            assert not restoration.layout_ready.is_set(), 'released by a layout that started before its request'
            await pilot.pause()
            assert restoration.layout_ready.is_set(), 'the next layout answers the request'
            window.history_restoration = None
            assert app._exception is None
            print(f'PASS stepped layout: {pauses} pauses, previous scene between steps, '
                  'restoration waits for the layout after its request, scene equals one-shot')


if __name__ == '__main__':
    asyncio.run(main())
