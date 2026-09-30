"""Loaded transcript readers retain intent through real geometry and key input."""

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from runtime_fixture import ToadApp
from toad.widgets.transcript_history import TranscriptHistory


class ReaderFrameApp(ToadApp):
    observed_window = None
    phase = "startup"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.frames = []

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        window = self.observed_window
        if (window is not None and renderable is not None and not self._batch_count
                and window.display and self.selected_session.conversation.window is window):
            region = window.scrollable_content_region
            strips = screen._compositor.render_strips()
            self.frames.append(dict(
                clock=monotonic(), phase=self.phase, y=window.scroll_y,
                maximum=window.max_scroll_y, follows_tail=window.follows_tail,
                paint="\n".join(strip.crop(region.x, region.right).text
                                for strip in strips[region.y:region.bottom]),
            ))


async def main():
    evidence = Path(os.environ["READER_GEOMETRY_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    app = None
    violations = []
    try:
        with TemporaryDirectory(prefix="reader-geometry-", dir=os.environ["TMPDIR"]) as directory:
            root = Path(directory)
            os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                              XDG_CONFIG_HOME=str(root / "config"),
                              XDG_STATE_HOME=str(root / "state"),
                              XDG_DATA_HOME=str(root / "data"))
            app = ReaderFrameApp(project_dir=str(root))
            async with app.run_test(size=(100, 35)) as pilot:
                await pilot.pause()
                conversation = app.selected_session.conversation
                cursor = TranscriptCursor("loaded-history", 1)
                page = TranscriptPage(tuple(
                    AssistantTranscript(f"Saved record {i}\n\n" + "\n".join(
                        f"- saved item {j}" for j in range(20))) for i in range(8)
                ), cursor, cursor, False, False)
                history = await conversation.post(TranscriptHistory(page))
                window = conversation.window
                app.observed_window = window
                await pilot.pause()
                window.focus(scroll_visible=False)
                await pilot.press("home")
                await pilot.wait_for_scheduled_animations()
                await pilot.press(*(["down"] * 5))
                await pilot.wait_for_scheduled_animations()
                await pilot.pause()
                position = window.scroll_y
                assert position > 0 and position < window.max_scroll_y, (position, window.max_scroll_y)
                assert not window.follows_tail
                conversation.prompt.text = "Retained reader draft"
                # Increase the real viewport until its bottom meets the reader.
                # The committed content has not changed and no scroll key was sent.
                app.phase = "geometry-meets-reader"
                height = int(35 + window.max_scroll_y - position)
                await pilot.resize_terminal(100, height)
                await pilot.pause()
                assert window.max_scroll_y == position, (position, window.max_scroll_y, height)
                assert window.scroll_y == position
                if window.follows_tail:
                    violations.append("Layout reacquired follow without reader input")

                app.phase = "geometry-restored"
                await pilot.resize_terminal(100, 35)
                await pilot.pause()
                if window.scroll_y != position or window.follows_tail:
                    violations.append(f"Geometry expansion lost offset {position}: y={window.scroll_y}, follow={window.follows_tail}")
                assert conversation.prompt.text == "Retained reader draft"
                assert history.is_attached

                # Moving down to the actual bottom still rejoins native follow.
                app.phase = "downward-rejoin"
                window.focus(scroll_visible=False)
                await pilot.press("pagedown")
                await pilot.wait_for_scheduled_animations()
                await pilot.pause()
                if not window.follows_tail or window.scroll_y != window.max_scroll_y:
                    violations.append("Downward movement did not rejoin follow at the bottom")
                app.phase = "upward-release"
                await pilot.press("pageup")
                await pilot.wait_for_scheduled_animations()
                await pilot.pause()
                if window.follows_tail:
                    violations.append("Upward movement did not release follow")
                # Explicit terminal End still owns the return to following.
                app.phase = "explicit-end"
                window.focus(scroll_visible=False)
                await pilot.press("end")
                await pilot.pause()
                if not window.follows_tail or window.scroll_y != window.max_scroll_y:
                    violations.append("End did not follow the actual bottom")
                final_paint = app.frames[-1]["paint"]
                app.phase = "stationary"
                await pilot.pause(.3)
                if not window.follows_tail or window.scroll_y != window.max_scroll_y:
                    violations.append("Stationary history lost tail position or follow")
                if app.frames[-1]["paint"] != final_paint:
                    violations.append("Stationary history changed paint")
                assert app._exception is None
                assert not violations, violations
            await asyncio.get_running_loop().shutdown_default_executor()
    finally:
        if app is not None:
            (evidence / "frames.json").write_text(json.dumps(app.frames, indent=2))
            (evidence / "violations.json").write_text(json.dumps(violations, indent=2))
    print("READER_GEOMETRY_DOWNWARD_REJOIN_UPWARD_RELEASE_END_STATIONARY_PASS")


if __name__ == "__main__":
    asyncio.run(main())
