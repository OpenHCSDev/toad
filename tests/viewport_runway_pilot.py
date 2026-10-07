"""Actual native bodies retain a spatial runway through idle and reversal."""

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from importlib.resources import files

from agent_comms.comms import Comms
from textual import events
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse


class RunwayApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')
    observed_window = None
    phase = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.scroll_frames = []

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        window = self.observed_window
        if window is None or self.phase is None or renderable is None or self._batch_count:
            return
        region = window.scrollable_content_region
        text = '\n'.join(strip.crop(region.x, region.right).text
                         for strip in screen._compositor.render_strips()[region.y:region.bottom])
        self.scroll_frames.append(dict(
            clock=monotonic(), phase=self.phase, y=window.scroll_y,
            nonwhite=len(''.join(text.split())),
            visible_ready=window.document_viewport.visible_bodies_ready,
        ))


async def main():
    evidence = Path(os.environ["RUNWAY_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="native-runway-", dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        Comms(root / "wire").messaging.initialize_private_initial_protocol()
        app = RunwayApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            window = view.window
            viewport = window.document_viewport
            docs = [AgentResponse(f"## Native runway {i}\n\n" + "\n\n".join(
                f"Paragraph {j} has actual native Markdown geometry." for j in range(4)),
                paginate=False) for i in range(48)]
            await view.contents.mount(*docs)

            async def settled():
                async with asyncio.timeout(15):
                    while viewport._worker is not None or viewport._pending or not viewport.visible_bodies_ready:
                        await pilot.pause(.02)
                await pilot.pause(viewport.lookahead.idle_seconds + .05)

            await settled()
            window.focus(scroll_visible=False)
            await pilot.press("end")
            await settled()
            # End's real binding focuses the prompt; subsequent page keys
            # must be delivered to the actual message area, not its editor.
            window.focus(scroll_visible=False)
            await pilot.pause(.05)
            assert app.screen.focused is window
            for _ in range(8):
                await pilot.press("pageup")
            await settled()
            visible = app.screen._compositor.visible_widgets
            indexes = [i for i, body in enumerate(docs) if body in visible]
            assert indexes and min(indexes) > 0 and max(indexes) < len(docs) - 1
            sides = {}
            for name, candidates in (("before", reversed(docs[:min(indexes)])),
                                     ("after", iter(docs[max(indexes) + 1:]))):
                rows = 0
                for body in candidates:
                    if not body.body_ready:
                        break
                    rows += body.measured_rows
                sides[name] = rows
            baseline = viewport.budget.runway_rows(window.size.height)
            receipt = {"boundary": "actual source ToadApp/native widget journey, not physical capture",
                       "viewport_rows": window.size.height,
                       "configured_viewports": app.settings.ui.history_buffer_viewports,
                       "baseline_rows": baseline, "ready_runway_rows": sides,
                       "travel_rows_at_idle": viewport.lookahead.travel_rows,
                       "warm_widgets": sum(1 + len(body.walk_children())
                                           for key in viewport._warm.values()
                                           if (body := key()) is not None),
                       "widget_limit": viewport.budget.widget_limit(window.size.height),
                       "prepared_bytes": app.preparation.retained_bytes,
                       "byte_limit": app.preparation.max_bytes}
            (evidence / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            assert all(rows >= baseline for rows in sides.values()), receipt
            assert receipt["warm_widgets"] <= receipt["widget_limit"], receipt
            assert receipt["prepared_bytes"] <= receipt["byte_limit"], receipt
            assert viewport.lookahead.travel_rows == 0
            app.settings.ui.history_buffer_viewports = 1
            await pilot.pause(.05)
            assert viewport.budget.buffer_viewports == 1
            assert viewport.lookahead.ahead_rows(window.size.height) == window.size.height
            app.settings.ui.history_buffer_viewports = 3
            await settled()
            assert viewport.budget.buffer_viewports == 3
            # Continuous native key delivery can arrive during an admitted
            # capture/restore await. Observe actual committed frames, without
            # holding or replacing the viewport's workers or renderer.
            app.observed_window = window
            burst = []
            window.release_anchor()
            window.scroll_to(y=window.max_scroll_y / 2, animate=False, immediate=True)
            await settled()
            for key_name in ('pageup', 'pagedown', 'pageup'):
                window.focus(scroll_visible=False)
                app.phase = key_name
                started = monotonic()
                for _ in range(12):
                    key = events.Key(key_name, None)
                    key.set_sender(app)
                    app._driver.send_message(key)
                    await asyncio.sleep(.025)
                await settled()
                frames = [frame for frame in app.scroll_frames if frame['clock'] >= started]
                assert frames and all(frame['visible_ready'] and frame['nonwhite'] for frame in frames), frames
                burst.append(dict(key=key_name, inputs=12, frames=len(frames),
                                  changed_positions=len({frame['y'] for frame in frames}),
                                  max_frame_gap=max((right['clock'] - left['clock']
                                                     for left, right in zip(frames, frames[1:])), default=0)))
            app.phase = None
            receipt['continuous_native_scroll'] = burst
            receipt['committed_scroll_frames'] = app.scroll_frames
            receipt["configuration_reversible"] = True
            window.focus(scroll_visible=False)
            await pilot.press("pagedown", "pageup", "end")
            await settled()
            assert window.follows_tail and window.scroll_y == window.max_scroll_y
            assert app._exception is None
            (evidence / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
