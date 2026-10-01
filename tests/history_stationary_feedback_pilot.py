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


async def main(output, *, compact=False):
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
            try:
                samples.append(sample("before-single-pageup"))
                await pilot.press("pageup")
                samples.append(sample("after-single-pageup"))
                for index in range(12):
                    await pilot.pause(.1)
                    samples.append(sample(f"stationary-{index}"))
            finally:
                sys.setprofile(None)
            receipt = {"scope": "source actual Toad/native stationary counter; not physical acceptance",
                       "compact_records": compact,
                       "samples": samples, "page_calls": calls,
                       "agent_bound": view.agent is not None,
                       "exception": str(app._exception)}
            (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt), flush=True)
            assert view.agent is None and app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), compact="--compact" in sys.argv[2:]))
