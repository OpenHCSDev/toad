"""Original fork/input journey, accepted queue handoff and native cancellation.

Only the provider is controlled. Record the original compositor updates without
asking for a full render, changing the driver or substituting protocol facts.
The existing terminal tools can review these same ANSI updates offline.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
from time import monotonic_ns

from agent_comms.acp_extension import InputStartedUpdate, PromptRequest, QueueItem
from agent_comms.field_codec import FieldCodec
from agent_comms.input_disposition import InputDispositions
from textual._compositor import CompositorUpdate

from first_fork_native_installed_pilot import InstalledApp as ForkApp, acceptance as fork_acceptance
from l0a_native_installed_pilot import main, until, response_painted
from saved_state_user_journey_pilot import submit_editor
from toad.widgets.committed_presentation import StartedInputClaim
from toad.widgets.prompt import SendNow
from toad.widgets.user_input import UserInput


@dataclass(frozen=True)
class SubmissionObservation:
    request: PromptRequest
    started_receipt: InputStartedUpdate | None


@dataclass(frozen=True)
class InputPaintFrame:
    observed_ns: int
    width: int
    height: int
    ansi: str
    driver: str
    headless: bool
    session_id: str | None
    submissions: tuple[SubmissionObservation, ...]
    queue: tuple[QueueItem, ...]
    mounted_starts: tuple[InputStartedUpdate, ...]


class InstalledApp(ForkApp):
    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if (self._batch_count or screen is not self.screen
                or not isinstance(renderable, CompositorUpdate)):
            return
        view = self.selected_session.conversation
        managed = view is not None and view.agent is not None
        frame = InputPaintFrame(
            monotonic_ns(), self.size.width, self.size.height,
            renderable.render_segments(self.console), type(self._driver).__name__,
            self.is_headless, view.agent.session_id if managed else None,
            tuple(SubmissionObservation(item.request, item.started_receipt)
                  for item in view.submissions.active if item.current) if managed else (),
            view.submissions.queue_projection.items if managed else (),
            tuple(block.commit_claim.source for block in view.contents.query(UserInput)
                  if isinstance(block.commit_claim, StartedInputClaim)) if managed else (),
        )
        with (Path(os.environ['L0A_EVIDENCE']) / 'input-frames.jsonl').open('a') as output:
            output.write(json.dumps(FieldCodec.encode(frame)) + '\n')


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    # Preserve the original failed first-fork oracle, including answer paint once.
    await fork_acceptance(app, pilot, agent, comms, entered, release, hold_next, requests)
    view = app.selected_session.conversation
    agent = view.agent
    evidence = Path(os.environ['L0A_EVIDENCE'])
    records = []

    entered.clear(); release.clear(); hold_next.set()
    await submit_editor(pilot, view.prompt.prompt_text_area, 'VISIBILITY_BUSY_TURN')
    await until(pilot, entered.is_set)
    assert len(requests) == 3
    await submit_editor(pilot, view.prompt.prompt_text_area, 'VISIBILITY_QUEUED_FOLLOWUP')
    await until(pilot, lambda: any(row.text == 'VISIBILITY_QUEUED_FOLLOWUP'
                                  for row in agent.queue_attachment.projection.items))
    queued = next(row for row in agent.queue_attachment.projection.items
                  if row.text == 'VISIBILITY_QUEUED_FOLLOWUP')
    rows = InputDispositions(comms.root / InputDispositions.filename)
    assert rows.read().lookup('acp:' + queued.input_id).unresolved
    assert not view.prompt.text
    records.append({'phase': 'accepted_pending', 'input_id': queued.input_id,
                    'queue': FieldCodec.encode(agent.queue_attachment.projection)})
    assert await pilot.click(SendNow)
    release.set()
    await until(pilot, lambda: len(requests) == 4 and not comms.registry.require(agent.session_id).executing)
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_4'))
    row = rows.read().lookup('acp:' + queued.input_id)
    assert row.has_started and row.native_id
    records.append({'phase': 'native_started', 'input_id': queued.input_id,
                    'native_id': row.native_id})
    native_rows = [json.loads(line) for line in Path(
        comms.registry.require(agent.session_id).session_file).read_text().splitlines()]
    assert sum(item.get('message', {}).get('inputId') == row.native_id
               for item in native_rows) == 1
    assert not agent.queue_attachment.projection.items
    await until(pilot, lambda: not view.submissions.active)

    entered.clear(); release.clear(); hold_next.set()
    await submit_editor(pilot, view.prompt.prompt_text_area, 'VISIBILITY_CANCEL_STARTED')
    await until(pilot, entered.is_set)
    assert len(requests) == 5
    await pilot.press('escape', 'escape')
    await until(pilot, lambda: not comms.registry.require(agent.session_id).executing
                and agent.presentation.prompt_in_flight == 0)
    release.set()
    await until(pilot, lambda: not view.submissions.active)
    records.append({'phase': 'cancelled_after_native_start',
                    'delivery': await agent.controller.input_delivery(include_history=True)})
    (evidence / 'input-handoff.json').write_text(json.dumps(records, indent=2) + '\n')
    assert len(requests) == 5, 'An original input was replayed'
    assert app._exception is None


def review_frames(path: Path):
    """Replay real incremental updates using the existing terminal dependency."""
    import pyte

    frames = tuple(FieldCodec.decode(InputPaintFrame, json.loads(line))
                   for line in path.read_text().splitlines())
    assert frames, 'No original compositor updates were captured'
    terminal = pyte.Screen(frames[0].width, frames[0].height)
    stream = pyte.Stream(terminal)
    observed = {}
    painted = set()
    for frame in frames:
        terminal.resize(lines=frame.height, columns=frame.width)
        stream.feed(frame.ansi)
        for submission in frame.submissions:
            if submission.started_receipt is None and submission.request.input_id not in painted:
                observed.setdefault(submission.request.input_id, submission.request.user_text)
        for queued in frame.queue:
            if queued.input_id not in painted:
                observed.setdefault(queued.input_id, queued.text)
        for start in frame.mounted_starts:
            if start.input_id not in painted:
                observed.setdefault(start.input_id, start.text)
        text = '\n'.join(terminal.display)
        starts = {source.input_id for source in frame.mounted_starts}
        for input_id, marker in tuple(observed.items()):
            # Check the selected request through its first actual native paint.
            # These are offline measurement sets, never application state.
            relevant = (any(item.request.input_id == input_id for item in frame.submissions)
                        or any(item.input_id == input_id for item in frame.queue)
                        or input_id in starts)
            if not relevant:
                continue
            assert marker and text.count(marker) == 1, (
                input_id, frame.observed_ns, text.count(marker or ''), text)
            if input_id in starts:
                painted.add(input_id)
                observed.pop(input_id)
    assert not observed, ('Inputs lacked a native paint in the completed journey', observed)
    return {'frames': len(frames), 'drivers': sorted({frame.driver for frame in frames}),
            'headless': sorted({frame.headless for frame in frames}),
            'native_painted_request_ids': sorted(painted)}


if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance,
                     expected_response_disconnects=frozenset({3, 5}),
                     provider_request_budget=5,
                     headless=os.environ.get('INPUT_VISIBILITY_TERMINAL') != '1',
                     fixture_stage=Path(os.environ['INPUT_VISIBILITY_FIXTURE'])))
    evidence = Path(os.environ['L0A_EVIDENCE'])
    (evidence / 'input-visibility-review.json').write_text(json.dumps(
        review_frames(evidence / 'input-frames.jsonl'), indent=2) + '\n')
