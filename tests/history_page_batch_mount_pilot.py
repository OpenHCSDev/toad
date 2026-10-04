"""Count original native page admissions without a provider or public root.

Exercises older/newer admission under the existing window publication fence.
The source counter proves ordered custody and transaction count, not physical
cold-start latency or CPU improvement.
"""

import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_comms.comms import Comms
from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from textual.widget import Widget
from toad.app import ToadApp
from toad.widgets.transcript_history import TranscriptHistory


async def main(output):
    output.mkdir(parents=True, exist_ok=False)
    results = []
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
            f"## Original record {index}\n\nNative ordered admission paragraph.",
        ) for index in range(32)), TranscriptCursor(source, 0),
            TranscriptCursor(source, 32), False, False)

        async def loader(**kwargs):
            raise AssertionError("Complete source must not read a transport page")

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            await view.transcript.suspend()
            await view.window.document_viewport.suspend_source()
            history = TranscriptHistory(page, loader=loader)
            operation = history.reserve_source_work()
            try:
                await view.post(history)
                await pilot.pause(.05)
                resource = history.pages[0]

                async def admit(older):
                    snapshot = history.source_snapshot()
                    children = tuple(resource.fragment_views)
                    calls = []

                    def trace(frame, event, arg):
                        if (event == "call" and frame.f_code is Widget.mount.__code__
                                and frame.f_locals["self"] is resource):
                            calls.append(len(frame.f_locals["widgets"]))

                    async with view.window.history_lock:
                        async with view.window.preserve_history(children[0]):
                            sys.setprofile(trace)
                            try:
                                await resource.extend(older, lambda: snapshot.current(history))
                            finally:
                                sys.setprofile(None)
                            current = tuple(resource.fragment_views)
                            results.append({
                                "direction": "older" if older else "newer",
                                "mount_transactions": calls,
                                "admitted_range": [resource.start, resource.stop],
                                "ordered_original_fragments": tuple(child.fragment for child in current)
                                    == resource.fragments[resource.start:resource.stop],
                                "previous_children_retained": all(child in current for child in children),
                                "all_children_mounted": all(child._mounted_event.is_set() for child in current),
                                "publication_fence_held": view.window.history_lock.locked(),
                            })

                await admit(True)
                async with view.window.history_lock:
                    async with view.window.preserve_history(resource.fragment_views[0]):
                        resource.trim(resource.batch_size, older=False)
                await admit(False)
                await admit(False)  # Complete local range performs no mount.
                receipt = {
                    "scope": "actual source Toad/native admission; not installed physical/CPU acceptance",
                    "cases": results,
                    "agent_bound": view.agent is not None,
                    "exception": str(app._exception),
                }
                (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
                print(json.dumps(receipt), flush=True)
                assert all(case["ordered_original_fragments"] and case["previous_children_retained"]
                           and case["all_children_mounted"] and case["publication_fence_held"]
                           for case in results)
                assert results[0]["mount_transactions"] == [resource.batch_size]
                assert results[1]["mount_transactions"] == [resource.batch_size]
                assert results[2]["mount_transactions"] == []
                assert view.agent is None and app._exception is None
            finally:
                history.finish_source_work(operation)
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
