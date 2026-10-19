"""Textual-facing: the history window keeps a reader's position through a taller terminal and rejoins the tail only on real reader input."""

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import NativeTranscriptCursor, TranscriptPage
from support.roots import FIXTURE_SNAPSHOT

from toad.widgets.presentation_window import PresentationBudget
from toad.widgets.transcript_history import TranscriptHistory


async def test_reader_keeps_position_through_geometry_and_rejoins_the_tail_on_input(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        app, pilot = ui.textual
        conversation = ui.conversation
        cursor = NativeTranscriptCursor("loaded-history", 1)
        page = TranscriptPage(tuple(
            AssistantTranscript(f"Saved record {i}\n\n" + "\n".join(f"- saved item {j}" for j in range(20)))
            for i in range(8)), cursor, cursor, False, False, FIXTURE_SNAPSHOT)
        history = await conversation.post(
            TranscriptHistory(page, budget=PresentationBudget(max_items=240, batch_items=240)))  # every record drawn at once
        window = conversation.window
        paints = []
        display = app._display

        def record(screen, renderable):
            if renderable is not None and not app._batch_count and window.display:
                region = window.scrollable_content_region
                paints.append("\n".join(strip.crop(region.x, region.right).text
                                        for strip in screen._compositor.render_strips()[region.y:region.bottom]))
            return display(screen, renderable)

        app._display = record
        await ui.until(lambda: window.max_scroll_y > 100, why="a scrollable history")
        window.focus(scroll_visible=False)
        await ui.press("home")
        await pilot.wait_for_scheduled_animations()
        await ui.press(*(["down"] * 5))
        await pilot.wait_for_scheduled_animations()
        await ui.step()
        position = window.scroll_y
        assert 0 < position < window.max_scroll_y, (position, window.max_scroll_y)
        assert not window.follows_tail
        await ui.write_draft("Retained reader draft")
        # Make the viewport tall enough that its bottom meets the reader, with no scroll key sent.
        await ui.resize(100, int(35 + window.max_scroll_y - position))
        await ui.until(lambda: window.max_scroll_y == position, why="the taller viewport")
        assert window.scroll_y == position
        assert not window.follows_tail, "Layout reacquired follow without reader input"

        await ui.resize(100, 35)
        assert window.scroll_y == position and not window.follows_tail, (
            f"Geometry expansion lost offset {position}: y={window.scroll_y}, follow={window.follows_tail}")
        assert ui.draft() == "Retained reader draft"
        assert history.is_attached

        window.focus(scroll_visible=False)

        async def page_down_to_the_bottom():
            # Older fragments are admitted as the reader nears the edge, so the bottom takes several pages.
            await ui.press("pagedown")
            await pilot.wait_for_scheduled_animations()
            return window.follows_tail and window.scroll_y == window.max_scroll_y

        await ui.until(page_down_to_the_bottom, why="downward movement to rejoin the tail")
        await ui.press("pageup")
        await pilot.wait_for_scheduled_animations()
        await ui.until(lambda: not window.follows_tail, why="upward movement to release the tail")
        window.focus(scroll_visible=False)
        await ui.press("end")
        await ui.until(lambda: window.follows_tail and window.scroll_y == window.max_scroll_y,
                       why="End to follow the actual bottom")
        await ui.step(0.3)
        last = paints[-1]
        await ui.step(0.3)
        assert window.follows_tail and window.scroll_y == window.max_scroll_y, "Stationary history lost the tail"
        assert paints[-1] == last, "Stationary history changed paint"
