"""Observe native page admission after one PageUp and no further gestures.

Actual Toad application/native history, source-only diagnostic. No Agent,
provider, public source or alternate viewport. Counts initial function entry,
not coroutine resumes. Physical observation belongs to the installed operator.
"""

import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_comms.comms import Comms
from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from toad.app import ToadApp
from toad.widgets.transcript_history import TranscriptHistory, TranscriptPageView


async def main(output, *, compact=False, input_paging=False, scroll_trace=False):
    output.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(dir=output) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        service = Comms(root / "wire")
        service.messaging.initialize_private_initial_protocol()
        source = str(root / "saved-source")
        page = TranscriptPage(tuple(AssistantTranscript(
            f"- Saved source record {index}." if compact else
            f"## Saved source record {index}\n\n"
            + "\n\n".join(f"Original paragraph {row}." for row in range(4)),
        ) for index in range(96)), TranscriptCursor(source, 0),
            TranscriptCursor(source, 96), False, False)

        async def loader(**kwargs):
            raise AssertionError("Complete original source must not read transport")

        calls, samples = [], []
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            await view.transcript.suspend()
            history = TranscriptHistory(page, loader=loader)
            await view.post(history)
            await pilot.pause(.3)
            view.window.focus()
            await pilot.pause(.05)
            started = monotonic()

            def sample(label):
                w = view.window
                return {"label": label, "seconds": monotonic() - started,
                        "scroll_y": w.scroll_y, "maximum": w.max_scroll_y,
                        "follows_tail": w.follows_tail,
                        "demand": type(w.document_viewport.lookahead.demand).__name__,
                        "travel_rows": w.document_viewport.lookahead.travel_rows,
                        "body_evictions": w.document_viewport.body_evictions,
                        "pages": [[p.start, p.stop] for p in history.pages]}

            observed = {f.__code__: f.__name__ for f in
                        (TranscriptPageView.extend, TranscriptPageView.trim)}

            def trace(frame, event, arg):
                if (event == "call" and frame.f_code in observed and len(calls) < 200
                        and frame.f_lineno == frame.f_code.co_firstlineno):
                    calls.append(sample(observed[frame.f_code]) |
                                 {"older": frame.f_locals["older"]})

            sys.setprofile(trace)
            observation = None
            if scroll_trace:
                import importlib.util
                path = Path(__file__).resolve().parents[1] / "tools/performance/scroll_travel_observation.py"
                spec = importlib.util.spec_from_file_location("scroll_travel_observation", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                observation = module.install(expected_pid=os.getpid(), output=output / "scroll-travel.jsonl")
            try:
                samples.append(sample("before-single-pageup"))
                if input_paging:
                    editor = view.prompt.prompt_text_area
                    editor.load_text("Original retained draft")
                    document, undo = editor.document, editor.history
                    assert await pilot.click(editor)
                    await pilot.pause(.05)
                    assert editor.has_focus
                    editor.move_cursor((0, 9))
                    selection = editor.selection
                await pilot.press("pageup")
                samples.append(sample("after-single-pageup"))
                for index in range(12):
                    await pilot.pause(.1)
                    samples.append(sample(f"stationary-{index}"))
                if input_paging:
                    assert not view.window.follows_tail
                    offset = view.window.scroll_y
                    await pilot.press("pagedown")
                    await pilot.pause(.25)
                    samples.append(sample("after-input-pagedown"))
                    assert view.window.scroll_y > offset
                    assert editor.has_focus and editor.selection == selection
                    assert editor.text == "Original retained draft"
                    assert editor.document is document and editor.history is undo
                    await pilot.press("left", "right")
                    assert editor.selection == selection
                    editor.history.checkpoint()
                    await pilot.press("backspace")
                    assert len(editor.text) == len("Original retained draft") - 1
                    await pilot.press("ctrl+z")
                    assert editor.text == "Original retained draft"
                    projection = app.workspace_chrome.channels.roster.projection
                    original_timer = projection.timer
                    assert original_timer._interval == 1 / 30
                    app.settings.sidebar.spinner_frames_per_second = 60
                    await pilot.pause(.05)
                    assert projection.timer is not original_timer
                    assert original_timer._task is None and original_timer._callback is None
                    assert projection.timer._interval == 1 / 60
                    for invalid in (0, 61):
                        try:
                            type(app.settings.sidebar).spinner_frames_per_second.parse(invalid)
                        except ValueError:
                            pass
                        else:
                            raise AssertionError("Sidebar animation bound was not enforced")
            finally:
                sys.setprofile(None)
                if observation is not None:
                    observation.close()
            receipt = {"scope": "source actual Toad/native stationary counter; not physical acceptance",
                       "compact_records": compact,
                       "input_paging_and_cadence": input_paging,
                       "samples": samples, "page_calls": calls,
                       "agent_bound": view.agent is not None,
                       "exception": str(app._exception)}
            (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt), flush=True)
            assert view.agent is None and app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), compact="--compact" in sys.argv[2:],
                     input_paging="--input" in sys.argv[2:], scroll_trace="--scroll-trace" in sys.argv[2:]))
