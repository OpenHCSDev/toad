"""Textual-facing: Textual's reflow clamps and the window's anchor compensation are geometry, not scroll input, for the preparation demand.

Not carried over from the old script: the sys.setprofile trace of anchor methods, the identity of the
demand object across an idle expiry, the per-message body readiness wait, and the view-level mutation roots (those
owners no longer exist).
"""

from dataclasses import replace

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage

from toad.widgets.transcript_history import TranscriptHistory


async def test_trim_and_resize_reflow_are_not_travel_samples_but_a_key_is(workspace):
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        window = view.window
        # Keep the idle expiry from replacing the demand during the check.
        window.presentation_budget = replace(window.presentation_budget, scroll_idle_seconds=5)
        histories = []
        for index in range(3):
            cursor = TranscriptCursor(f"saved-{index}", 1)
            text = f"## SAVED SOURCE {index}\n\n" + "\n".join(f"- saved record {index}, row {row}" for row in range(120))
            history = TranscriptHistory(TranscriptPage((AssistantTranscript(text),), cursor, cursor, False, False))
            histories.append(history)
            await view.contents.mount(history)
        await ui.until(lambda: all(history.is_mounted for history in histories), why="three histories")
        marker = histories[-1]
        window.release_anchor()
        window.scroll_to_widget(marker, animate=False, immediate=True, top=True)
        await ui.step()

        # Removing an earlier history makes Textual clamp the reader before the anchor compensates.
        before = dict(y=window.scroll_y, marker_y=marker.region.y, revision=window.scroll_revision)
        samples, changes = [], []
        observe = window.lookahead.observe

        def sample(position):
            result = observe(position)
            samples.append(dict(restoring=window._restoring, sampled=result))
            return result

        window.lookahead.observe = sample
        window.watch(window, "scroll_y", lambda old, new: changes.append(window._restoring), init=False)
        demand = window.lookahead.demand
        async with window.preserve_history(marker, root=view.contents):
            await histories[0].remove()
        await ui.step()
        assert changes, "The clamp and compensation boundary was not exercised"
        assert all(changes), "Compensation moved the reader outside a restoration"
        assert window.scroll_revision == before["revision"]
        assert marker.region.y == before["marker_y"], "The anchor was not held"
        assert window.lookahead.demand is demand, "Compensation changed the preparation demand"
        assert not any(item["sampled"] for item in samples if item["restoring"])

        # Resize also reflows with no anchor; its clamp is geometry.
        samples.clear()
        changes.clear()
        await ui.resize(120, 195)
        assert changes, "Resize did not clamp the reader"
        assert all(changes)
        assert not any(item["sampled"] for item in samples)
        assert window.lookahead.demand is demand

        # A real key is travel and is sampled outside any restoration.
        await ui.resize(120, 35)
        samples.clear()
        window.focus(scroll_visible=False)
        await ui.press("pagedown")
        await ui.until(lambda: any(item["sampled"] and not item["restoring"] for item in samples),
                       why="the key to be sampled as travel")
