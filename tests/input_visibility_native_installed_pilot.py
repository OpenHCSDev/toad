"""Original fork/input journey, accepted queue handoff and native cancellation.

Only the provider is controlled. Record the original compositor updates without
asking for a full render, changing the driver or substituting protocol facts.
The existing terminal tools can review these same ANSI updates offline.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections import namedtuple
from contextlib import asynccontextmanager, ExitStack
import signal
import pyte
import psutil
from agent_comms.child_process import ProcessIdentity, PidfdHandles
import json
import os
from pathlib import Path
from time import monotonic_ns

from agent_comms.acp_extension import InputStartedUpdate, PromptRequest, QueueItem
from agent_comms.field_codec import FieldCodec
from agent_comms.input_disposition import InputDispositions
from agent_comms.transcript_events import UserTranscript
from textual._compositor import CompositorUpdate

from first_fork_native_installed_pilot import InstalledApp as ForkApp, acceptance as fork_acceptance
from l0a_native_installed_pilot import main, until, response_painted
from saved_state_user_journey_pilot import prepare_editor
from toad.widgets.committed_presentation import StartedInputClaim
from toad.widgets.prompt import QueueSummary, SendNow
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
    queue_region: tuple[int, int, int, int]
    chat_region: tuple[int, int, int, int]

    def includes(self, region: tuple[int, int, int, int], x: int, y: int) -> bool:
        left, top, width, height = region
        return left <= x < left + width and top <= y < top + height


PaintedChar = namedtuple('PaintedChar', (*pyte.screens.Char._fields, 'paint_frame'))

class InputRaster(pyte.Screen):
    paint_frame = None

    @property
    def default_char(self):
        return PaintedChar(*super().default_char, self.paint_frame)

    def reset(self):
        super().reset()
        self.cursor.attrs = self.default_char

    def draw(self, data):
        self.cursor.attrs = self.cursor.attrs._replace(paint_frame=self.paint_frame)
        super().draw(data)

    def region_text(self, region):
        lines = []
        for y in range(self.lines):
            characters = []
            for x in range(self.columns):
                char = self.buffer[y][x]
                source = char.paint_frame
                characters.append(char.data if source is not None
                    and source.includes(region(source), x, y) else ' ')
            lines.append(''.join(characters))
        return '\n'.join(lines)


class BeforeDeliveryCapture:
    """One fixture receipt from original emitted ANSI, not widget state."""

    def __init__(self, text: str):
        self.text = text
        self.receipt = asyncio.get_running_loop().create_future()
        self.terminal = None
        self.stream = None

    def observe(self, frame: InputPaintFrame):
        if self.receipt.done():
            return
        if self.terminal is None:
            self.terminal = InputRaster(frame.width, frame.height)
            self.stream = pyte.Stream(self.terminal)
        self.terminal.paint_frame = frame
        self.terminal.resize(lines=frame.height, columns=frame.width)
        self.stream.feed(frame.ansi)
        requests = tuple(item.request for item in frame.submissions
                         if item.request.user_text == self.text and item.started_receipt is None)
        if len(requests) != 1:
            return
        request = requests[0]
        if any(start.input_id == request.input_id for start in frame.mounted_starts):
            return
        queue_text = self.terminal.region_text(lambda source: source.queue_region)
        chat_text = self.terminal.region_text(lambda source: source.chat_region)
        if queue_text.count(self.text) == 1 and chat_text.count(self.text) == 0:
            self.receipt.set_result(frame)

class InstalledApp(ForkApp):
    before_delivery_capture = None

    async def submit_editor(self, view, pilot, comms, text):
        await prepare_editor(pilot, view.prompt.prompt_text_area, text)
        # AgentReady precedes queued owner-metadata callbacks. Finish the native
        # editor/widget barrier while the worker can still answer those reads.
        await pilot.pause()
        async with self.input_presentation_gate(view, pilot, comms, text):
            await pilot.press('enter')

    @asynccontextmanager
    async def input_presentation_gate(self, view, pilot, comms, text):
        """Hold only this fixture's attested worker until pre-delivery paint."""
        owner = comms.registry.require(view.agent.session_id)
        identity = owner.process_identity
        assert identity is not None and owner.process_alive
        assert comms.root.resolve().is_relative_to(Path(os.environ['INPUT_VISIBILITY_FIXTURE']).resolve())
        process = psutil.Process(identity.pid)
        assert Path(process.environ()['AGENT_COMMS_ROOT']).resolve() == comms.root.resolve()
        assert process.cmdline()[1:3] == ['-m', 'agent_comms.worker']
        capture = BeforeDeliveryCapture(text)
        with ExitStack() as resources:
            descriptor = PidfdHandles.open_pidfd(identity.pid)
            resources.callback(os.close, descriptor)
            assert ProcessIdentity.capture(identity.pid) == identity
            PidfdHandles.signal_pidfd(descriptor, signal.SIGSTOP)
            try:
                await until(pilot, lambda: process.status() == psutil.STATUS_STOPPED)
                self.before_delivery_capture = capture
                yield
                await until(pilot, capture.receipt.done)
                frame = capture.receipt.result()
                request = next(item.request for item in frame.submissions
                               if item.request.user_text == text)
                dispositions = InputDispositions(comms.root / InputDispositions.filename)
                # Never block on a store potentially held by the suspended worker.
                # Canonical nonblocking lock failure exits through SIGCONT below.
                with dispositions.locked(shared=True, blocking=False):
                    row = dispositions.read().lookup('acp:' + request.input_id)
                assert row is None or not row.has_started
                assert ProcessIdentity.capture(identity.pid) == identity
                proof = {'original_request': FieldCodec.encode(request),
                         'held_worker': FieldCodec.encode(identity), 'private_root': str(comms.root),
                         'before_delivery_frame': FieldCodec.encode(frame),
                         'physical_queue_or_submitting_before_resume': True,
                         'authoritative_native_started': False, 'physical_enter': True}
                (Path(os.environ['L0A_EVIDENCE']) / f'before-delivery-{request.input_id}.json').write_text(
                    json.dumps(proof, indent=2) + '\n')
            finally:
                self.before_delivery_capture = None
                PidfdHandles.signal_pidfd(descriptor, signal.SIGCONT)
            assert comms.registry.require(owner.name).process_identity == identity

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
            tuple(view.prompt.query_one(QueueSummary).region) if managed else (0, 0, 0, 0),
            tuple(view.window.scrollable_content_region) if managed else (0, 0, 0, 0),
        )
        with (Path(os.environ['L0A_EVIDENCE']) / 'input-frames.jsonl').open('a') as output:
            output.write(json.dumps(FieldCodec.encode(frame)) + '\n')
        if self.before_delivery_capture is not None:
            self.before_delivery_capture.observe(frame)


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    # Preserve the original failed first-fork oracle, including answer paint once.
    await fork_acceptance(app, pilot, agent, comms, entered, release, hold_next, requests)
    view = app.selected_session.conversation
    agent = view.agent
    evidence = Path(os.environ['L0A_EVIDENCE'])
    records = []

    entered.clear(); release.clear(); hold_next.set()
    await app.submit_editor(view, pilot, comms, 'VISIBILITY_BUSY_TURN')
    await until(pilot, entered.is_set)
    assert len(requests) == 3
    await app.submit_editor(view, pilot, comms, 'VISIBILITY_QUEUED_FOLLOWUP')
    await until(pilot, lambda: any(row.text == 'VISIBILITY_QUEUED_FOLLOWUP'
                                  for row in agent.queue_attachment.projection.items))
    queued = next(row for row in agent.queue_attachment.projection.items
                  if row.text == 'VISIBILITY_QUEUED_FOLLOWUP')
    rows = InputDispositions(comms.root / InputDispositions.filename)
    assert rows.read().lookup('acp:' + queued.input_id).unresolved
    assert not view.prompt.text
    records.append({'phase': 'accepted_pending', 'input_id': queued.input_id,
                    'queue': FieldCodec.encode(agent.queue_attachment.projection)})
    control = view.prompt.query_one(SendNow)
    control.scroll_visible(animate=False, immediate=True)
    await until(pilot, lambda: control.region.width > 0 and control.region.height > 0
                and app.screen.get_widget_at(*control.region.offset)[0] is control)
    assert app.selected_session.conversation is view and view.agent is agent
    global_control = app.screen.query_one(SendNow)
    from toad.widgets.conversation import Conversation
    (evidence / 'queue-control-target.json').write_text(json.dumps({
        'selected_session': agent.session_id,
        'actual_target_owner': control.query_ancestor(Conversation).agent.session_id,
        'actual_target_region': tuple(control.region),
        'global_selector_owner': global_control.query_ancestor(Conversation).agent.session_id,
        'global_selector_region': tuple(global_control.region),
        'original_input_id': queued.input_id,
        'original_admission_unresolved': rows.read().lookup('acp:' + queued.input_id).unresolved,
    }, indent=2) + '\n')
    assert await pilot.click(control)
    release.set()
    await until(pilot, lambda: len(requests) == 4 and not comms.registry.require(agent.session_id).executing)
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_4'))
    row = rows.read().lookup('acp:' + queued.input_id)
    assert row.has_started and row.native_id
    records.append({'phase': 'native_started', 'input_id': queued.input_id,
                    'native_id': row.native_id})
    saved = comms.transcripts.thread_transcript_page(agent.session_id)
    assert sum(isinstance(event, UserTranscript) and event.native_id == row.native_id
               for event in saved.events) == 1
    assert not agent.queue_attachment.projection.items
    await until(pilot, lambda: not view.submissions.active)

    entered.clear(); release.clear(); hold_next.set()
    await app.submit_editor(view, pilot, comms, 'VISIBILITY_CANCEL_STARTED')
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
    frames = tuple(FieldCodec.decode(InputPaintFrame, json.loads(line))
                   for line in path.read_text().splitlines())
    assert frames, 'No original compositor updates were captured'
    terminal = InputRaster(frames[0].width, frames[0].height)
    stream = pyte.Stream(terminal)
    observed = {}
    painted = {}
    source_observed = {}
    first_paint = {}
    before_delivery_paint = {}

    for frame in frames:
        terminal.paint_frame = frame
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
        queue_text = terminal.region_text(lambda source: source.queue_region)
        chat_text = terminal.region_text(lambda source: source.chat_region)
        text = '\n'.join((queue_text, chat_text))
        for input_id in observed:
            source_observed.setdefault(input_id, frame.observed_ns)
        for input_id, marker in painted.items():
            assert text.count(marker) <= 1, (
                'Original input painted twice after handoff', input_id,
                frame.observed_ns, text.count(marker), text)
        starts = {source.input_id for source in frame.mounted_starts}
        for input_id, marker in tuple(observed.items()):
            # Check the selected request through its first actual native paint.
            # These are offline measurement sets, never application state.
            relevant = (any(item.request.input_id == input_id for item in frame.submissions)
                        or any(item.input_id == input_id for item in frame.queue)
                        or input_id in starts)
            if not relevant:
                continue
            occurrences = text.count(marker)
            if (input_id not in starts and queue_text.count(marker) == 1
                    and chat_text.count(marker) == 0
                    and not any(item.request.input_id == input_id and item.started_receipt is not None
                                for item in frame.submissions)):
                before_delivery_paint.setdefault(input_id, frame.observed_ns)
            # Source receipt/admission can precede its first presentation paint.
            # Measure that join; after physical presentation begins, no missing
            # frame is allowed through the original native user paint.
            if input_id not in first_paint:
                if not occurrences:
                    continue
                first_paint[input_id] = frame.observed_ns
            assert marker and occurrences == 1, (
                input_id, frame.observed_ns, text.count(marker or ''), text,
                '\n'.join(line for line in terminal.display if marker in line))
            if input_id in starts and chat_text.count(marker) == 1:
                assert input_id in before_delivery_paint, (
                    'No physical submission/queue before native user paint', input_id, frame.observed_ns)
                painted[input_id] = marker
                observed.pop(input_id)
    assert not observed, ('Inputs lacked a native paint in the completed journey', observed)
    return {'frames': len(frames), 'drivers': sorted({frame.driver for frame in frames}),
            'headless': sorted({frame.headless for frame in frames}),
            'native_painted_request_ids': sorted(painted),
            'before_delivery_paint_ns': before_delivery_paint,
            'source_to_first_paint_ns': {
                input_id: first_paint[input_id] - source_observed[input_id]
                for input_id in painted},
            'scope': 'original selected queue and native chat viewport; excludes status captions'}


if __name__ == '__main__':
    # Fail before starting any native owner if the existing review dependency
    # is missing; do not spend the fixture journey before discovering that.
    import pyte

    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance,
                     expected_response_disconnects=frozenset({3, 5}),
                     provider_request_budget=5,
                     headless=os.environ.get('INPUT_VISIBILITY_TERMINAL') != '1',
                     fixture_stage=Path(os.environ['INPUT_VISIBILITY_FIXTURE'])))
    evidence = Path(os.environ['L0A_EVIDENCE'])
    (evidence / 'input-visibility-review.json').write_text(json.dumps(
        review_frames(evidence / 'input-frames.jsonl'), indent=2) + '\n')
