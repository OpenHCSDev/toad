"""Profile eviction of actual native Markdown trees under the window budget.

No provider, ACP process, original thread or substituted application/body.
The profile covers only the synchronous warm-set trim, not paint latency.
"""

import asyncio
import cProfile
from dataclasses import replace
import json
import os
from pathlib import Path
import pstats
from tempfile import TemporaryDirectory
from time import process_time, monotonic

from agent_comms.comms import Comms
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets import viewport_body


async def main():
    evidence = Path(os.environ["TRIM_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="native-warm-trim-", dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        Comms(root / "wire").messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            manager = view.window.document_viewport
            manager.budget = replace(manager.budget, minimum_widgets=10000, widgets_per_row=0)
            docs = [AgentResponse(f"## Native body {i}\n\n" + "\n\n".join(
                f"Paragraph {j}: actual selectable Markdown source. " * 3 for j in range(20)),
                paginate=False) for i in range(24)]
            await view.contents.mount(*docs)
            async with asyncio.timeout(15):
                while any(not body.body_ready for body in docs) or manager._worker is not None:
                    await pilot.pause(.02)
            # Freeze the existing resource worker, not the widget trees. Trim
            # has no await between counting and eviction; this is its real DOM.
            await manager.suspend_source()
            original = tuple(manager._warm.items())
            widgets_before = sum(1 + len(owner.walk_children()) for _, key in original
                                 if (owner := key()) is not None)
            owner_count = sum(key() is not None for _, key in original)
            assert owner_count >= len(docs) and widgets_before > 400
            manager.budget = replace(manager.budget, minimum_widgets=100, widgets_per_row=0)
            profiler = cProfile.Profile()
            cpu, started = process_time(), monotonic()
            profiler.enable()
            await manager._trim_warm()
            profiler.disable()
            elapsed_cpu, elapsed_wall = process_time() - cpu, monotonic() - started
            profiler.dump_stats(str(evidence / "trim.prof"))
            stats = pstats.Stats(profiler)
            walks = sum(row[1] for (_, _, name), row in stats.stats.items()
                        if name == "walk_children")
            survivors = tuple(manager._warm.items())
            # LRU suffix remains intact and fits the unchanged widget budget.
            assert survivors == original[len(original) - len(survivors):]
            retained_widgets = sum(1 + len(owner.walk_children()) for _, key in survivors
                                   if (owner := key()) is not None)
            assert retained_widgets <= manager.budget.widget_limit(view.window.size.height)
            assert manager.body_evictions >= owner_count - len(survivors)
            # Same still-mounted trees and LRU order, without profiler hooks.
            # The viewport worker stays suspended throughout both measurements.
            manager._warm.clear()
            manager._warm.update(original)
            cpu, started = process_time(), monotonic()
            await manager._trim_warm()
            unprofiled_cpu, unprofiled_wall = process_time() - cpu, monotonic() - started
            assert tuple(manager._warm.items()) == survivors
            receipt = dict(source=str(Path(viewport_body.__file__).resolve()),
                           boundary="actual headless native resource trim; not installed/physical paint",
                           owner_count=owner_count, widgets_before=widgets_before,
                           retained_owners=len(survivors), retained_widgets=retained_widgets,
                           native_subtree_walks=walks, trim_cpu_seconds=elapsed_cpu,
                           trim_wall_seconds=elapsed_wall,
                           unprofiled_trim_cpu_seconds=unprofiled_cpu,
                           unprofiled_trim_wall_seconds=unprofiled_wall,
                           lru_order_preserved=True, budget_satisfied=True)
            (evidence / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt), flush=True)
            assert walks <= owner_count, "Warm eviction repeatedly walks the same native tree"
            manager.resume_source()
            await pilot.pause(.25)
            assert app._exception is None


if __name__ == "__main__":
    asyncio.run(main())
