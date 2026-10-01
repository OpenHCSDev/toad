"""Native saved-history trim must not become a new reader travel sample."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import Comms
from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from toad.app import ToadApp
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    evidence = Path(os.environ['REFLOW_TRAVEL_EVIDENCE']).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=evidence) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        Comms(root / 'wire').messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            await view.transcript.suspend()
            window = view.window
            # Retain this small original body cohort to isolate native extent
            # compensation from the separately tested resource admission bound.
            window.document_viewport.budget = replace(
                window.document_viewport.budget, minimum_widgets=1000,
                scroll_idle_seconds=5)
            histories = []
            for index in range(3):
                cursor = TranscriptCursor(f'saved-{index}', 1)
                text = f'## ORIGINAL SAVED SOURCE {index}\n\n' + '\n'.join(
                    f'- original saved record {index}, row {row}' for row in range(120))
                history = TranscriptHistory(TranscriptPage(
                    (AssistantTranscript(text),), cursor, cursor, False, False))
                histories.append(history)
                await view.contents.mount(history)
            await pilot.pause()
            viewport = window.document_viewport
            async with asyncio.timeout(10):
                while viewport._running or not viewport.visible_bodies_ready:
                    await pilot.pause(.02)
            marker = histories[-1]
            window.release_anchor()
            window.scroll_to_widget(marker, animate=False, immediate=True, top=True)
            await pilot.pause()
            # The last page plus native trailing space leaves a reader near the
            # end. Removing an earlier real page forces Textual's first reflow
            # to clamp it before the same source anchor is compensated.
            before = dict(y=window.scroll_y, maximum=window.max_scroll_y,
                          marker_y=marker.region.y, revision=window.scroll_revision)
            changes = []
            samples = []
            original_observe = viewport.lookahead.observe
            def observe(position):
                result = original_observe(position)
                samples.append(dict(position=position, restoring=window._restoring,
                                    sampled=result, demand=repr(viewport.lookahead.demand)))
                return result
            viewport.lookahead.observe = observe
            def changed(old, new):
                changes.append(dict(old=old, new=new, restoring=window._restoring,
                                    revision=window.scroll_revision))
            window.watch(window, 'scroll_y', changed, init=False)
            original_demand = viewport.lookahead.demand
            demand_before = repr(original_demand)
            async with window.preserve_history(marker):
                await histories[0].remove()
            await pilot.pause()
            after = dict(y=window.scroll_y, maximum=window.max_scroll_y,
                         marker_y=marker.region.y, revision=window.scroll_revision)
            trim_changes, trim_samples = changes[:], samples[:]
            trim_demand = repr(viewport.lookahead.demand)
            trim_same_demand = viewport.lookahead.demand is original_demand
            changes.clear()
            samples.clear()
            # Ordinary native resize also reflows the original window, without
            # an active prepend/trim anchor. Its clamp is geometry, not input.
            await pilot.resize_terminal(120, 195)
            await pilot.pause()
            resize = dict(y=window.scroll_y, maximum=window.max_scroll_y,
                          revision=window.scroll_revision, changes=changes[:],
                          samples=samples[:], demand_before=trim_demand,
                          demand_after=repr(viewport.lookahead.demand))
            await pilot.resize_terminal(120, 35)
            await pilot.pause()
            changes.clear()
            samples.clear()
            window.focus(scroll_visible=False)
            await pilot.press('pagedown')
            await pilot.wait_for_scheduled_animations()
            await pilot.pause()
            input_control = dict(changes=changes[:], samples=samples[:])
            receipt = dict(before=before, after=after, changes=trim_changes,
                           samples=trim_samples, demand_before=demand_before,
                           demand_after=trim_demand, resize=resize,
                           input_control=input_control,
                           same_demand=trim_same_demand,
                           source_resources=[id(item) for item in histories[1:]],
                           remaining_histories=len(window.histories),
                           agent_bound=view.agent is not None)
            (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            print(json.dumps(receipt), flush=True)
            assert trim_changes, 'The native clamp/compensation boundary was not exercised'
            assert all(item['restoring'] for item in trim_changes), receipt
            assert after['revision'] == before['revision'], receipt
            assert after['marker_y'] == before['marker_y'], receipt
            assert receipt['same_demand'], receipt
            assert receipt['demand_after'] == demand_before, receipt
            assert not receipt['agent_bound'], 'This source counter must not start ACP/native'
            assert resize['changes'], 'Native resize did not clamp this saved reader'
            assert all(item['restoring'] for item in resize['changes']), receipt
            assert not any(item['sampled'] for item in resize['samples']), receipt
            assert resize['demand_after'] == resize['demand_before'], receipt
            assert any(item['sampled'] and not item['restoring']
                       for item in input_control['samples']), receipt
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == '__main__':
    asyncio.run(main())
