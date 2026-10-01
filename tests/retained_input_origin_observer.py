"""Actual Toad ingress observer on the existing S2/S5 native private fixture.

The caller retains custody of its original RuntimeServer, native session and
provider. This helper opens the normal ACP client and Toad application on that
same root. It declares no new owner and never manufactures an author witness.
"""

import asyncio
import base64
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shlex
import sys

from agent_comms.field_codec import FieldCodec
from agent_comms.acp_extension import QueuePromptRequest
from agent_comms.input_disposition import InputDispositions
from agent_comms.native_entries import NativeEntry
from agent_comms.retained_task_facts import HumanInputTaskFact
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp


async def until(pilot, predicate, seconds=20):
    async with asyncio.timeout(seconds):
        while not predicate():
            await pilot.pause(.05)


@dataclass
class ActualS2Ingress:
    app: ToadApp
    pilot: object
    comms: object
    subject: object
    output: Path
    receipts: list = field(default_factory=list)

    def persist(self, phase):
        (self.output / 'actual-human-ingress.json').write_text(json.dumps({
            'phase': phase, 'core': __import__('agent_comms').__file__,
            'toad': __import__('toad').__file__, 'original_inputs_retried': 0,
            'receipts': self.receipts,
        }, indent=2))

    async def queue_followup(self, text):
        """Use the same original client while the caller holds its provider turn."""
        inputs = InputDispositions(self.comms.root / InputDispositions.filename)
        before = inputs.read()
        command = QueuePromptRequest(text, True)
        await self.app.selected_session.conversation.agent.send_prompt(text, request=command)
        await until(self.pilot, lambda: len(inputs.read().rows) == len(before.rows) + 1)
        row = inputs.read().lookup('acp:' + command.input_id)
        row.origin.require_human().author.require_registered(self.comms.registry.snapshot())
        assert row.source_text == text
        self.receipts.append({'queued_original': FieldCodec.encode(row)})
        self.persist('same_actual_controller_queued_original_human_followup')
        return row

    async def submit(self, text, *, image=None, while_running=None):
        view = self.app.selected_session.conversation
        agent = view.agent
        inputs = InputDispositions(self.comms.root / InputDispositions.filename)
        before = inputs.read()
        wire_sequence = self.comms.bus.log.latest_sequence()
        prompt = text
        if image is not None:
            attachment = Path(self.subject.worktree) / 's2-original-image.png'
            with attachment.open('xb') as stream:
                stream.write(base64.b64decode(image['data'], validate=True))
            prompt += ' @s2-original-image.png'
        await until(self.pilot, lambda: view.agent_ready)
        view.prompt.text = prompt
        view.prompt.prompt_text_area.focus()
        self.persist('before_actual_editor_enter')
        await self.pilot.press('enter')
        await until(self.pilot, lambda: len(inputs.read().rows) == len(before.rows) + 1)
        rows = inputs.read()
        new_keys = rows.rows.keys() - before.rows.keys()
        key, = new_keys
        original = rows.lookup(key)
        origin = original.origin.require_human()
        snapshot = self.comms.registry.snapshot()
        origin.author.require_registered(snapshot)
        assert original.source_text == prompt
        with self.comms.bus.log.locked():
            assert origin.root_id == self.comms.bus.log.read_metadata_unlocked().wire_root_id
        assert Path(agent.coordination.wire_root) == self.comms.root
        receipt = {'original': FieldCodec.encode(original),
                   'wire_sequence_before': wire_sequence}
        self.receipts.append(receipt)
        self.persist('actual_editor_enter_original_authored_reservation')

        await until(self.pilot, lambda: inputs.read().lookup(key).has_started, 30)
        if while_running is not None:
            await while_running(self, inputs.read().lookup(key))
        await until(self.pilot, lambda: not self.comms.registry.require(self.subject.name).executing, 30)
        document = InputDispositions(inputs.path).read()
        terminal = document.lookup(key)
        assert terminal.origin == origin
        assert isinstance(terminal.origin.retained_fact(terminal), HumanInputTaskFact)
        source = Path(self.comms.registry.require(self.subject.name).require_saved_session())
        with NativeEntry.open_evidence(source) as reader:
            header, entries = reader.observe()
        user, = [entry for entry in entries if entry.input_id == terminal.native_id]
        assert user.message.user
        replies = []
        original_turn_inputs = tuple(row for row in document.rows.values()
            if row.has_started and row.turn_id == terminal.turn_id)
        for entry in entries[entries.index(user) + 1:]:
            if entry.input_boundary and not any(
                    row.native_id == entry.input_id for row in original_turn_inputs):
                break
            if entry.final_reply:
                replies.append(entry)
        assert replies, 'Original native turn has no successful terminal reply'
        reply = replies[-1]
        body = reply.message.authoritative_text
        assert body, 'This controlled journey requires a nonempty original reply'

        def frame():
            window = view.window.region
            return '\n'.join(strip.crop(window.x, window.right).text
                for strip in self.app.screen._compositor.render_strips()[window.y:window.bottom])

        await until(self.pilot, lambda: body in frame())
        visible_occurrences = frame().count(body)
        self.app.export_screenshot(filename=str(self.output / f'original-reply-{len(self.receipts)}.svg'))
        receipt.update({
            'terminal': FieldCodec.encode(terminal), 'native_user_entry': user.id,
            'native_reply_entry': reply.id, 'native_header': FieldCodec.encode(header),
            'original_turn_input_bindings': [FieldCodec.encode(row) for row in original_turn_inputs],
            'actual_frame_body_occurrences': visible_occurrences,
            'frame_identity_limit': 'Equal bodies are not message identity; original native IDs are recorded separately.',
            'retained_fact': FieldCodec.encode(terminal.origin.retained_fact(terminal)),
        })
        self.persist('original_native_ids_terminal_reply_and_actual_frame')
        return terminal


@asynccontextmanager
async def _open_actual_s2_ingress(owner, subject, output):
    """Open one real client on the caller's original native/ACP fixture."""
    output = Path(output) / 'toad-ingress'
    output.mkdir(mode=0o700)
    environment = {
        'XDG_CONFIG_HOME': str(output / 'config'),
        'XDG_DATA_HOME': str(output / 'data'),
        'XDG_STATE_HOME': str(output / 'state'),
        'AGENT_COMMS_ROOT': str(owner._comms.root),
    }
    previous = {key: os.environ.get(key) for key in environment}
    os.environ.update(environment)

    def phase(name):
        (output / 'driver-resource-custody.json').write_text(json.dumps({
            'phase': name, 'original_root': str(owner._comms.root),
            'original_subject': FieldCodec.encode(subject.incarnation),
            'core': __import__('agent_comms').__file__, 'toad': __import__('toad').__file__,
            'new_owner_declared': False, 'original_inputs_retried': 0,
        }, indent=2))

    try:
        phase('before_actual_toad_constructor')
        definition = AgentDefinition.decode({
            'name': 'Original S2/S5 fixture', 'identity': 'original-s2-s5',
            'short_name': 's2-s5', 'protocol': 'acp',
            'run_command': {'*': shlex.join([sys.executable, '-m', 'agent_comms.acp'])},
        })
        app = ToadApp(agent_data=definition, project_dir=subject.worktree,
                      agent_session_id=subject.name)
        phase('before_actual_toad_run_test')
        async with app.run_test(headless=True, size=(160, 44)) as pilot:
            phase('actual_toad_run_test_yielded_before_saved_view_ready')
            await until(pilot, lambda: app.selected_session is not None)
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            await until(pilot, lambda: view.agent is not None)
            phase('actual_original_view_before_acp_attachment_settlement')
            await until(pilot, view.agent.session.settled.is_set)
            assert view.agent.session.connected
            await until(pilot, lambda: view.agent.queue_attachment.scope is not None)
            observer = ActualS2Ingress(app, pilot, owner._comms, subject, output)
            phase('actual_acp_attached_original_queue_scope')
            observer.persist('same_original_owner_actual_toad_acp_attached')
            try:
                yield observer
                assert app._exception is None
            except BaseException as error:
                observer.persist(f'original_failure_no_replay: {error!r}')
                raise
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@dataclass
class IsolatedS2Ingress:
    """One actual UI loop resource; original backend stays on the caller's loop."""

    observer: ActualS2Ingress
    loop: object

    async def run(self, operation):
        async def invoke():
            # Thread-safe scheduling inherits the caller's Context, not the
            # actual application's. Use Textual's existing context owner for
            # every UI operation; never recreate its ContextVar state here.
            with self.observer.app._context():
                return await operation

        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(invoke(), self.loop))

    async def queue_followup(self, text):
        return await self.run(self.observer.queue_followup(text))

    async def submit(self, text, *, image=None, while_running=None):
        caller = asyncio.get_running_loop()

        async def callback(observer, original):
            return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(
                while_running(self, original), caller))

        return await self.run(self.observer.submit(text, image=image,
            while_running=callback if while_running is not None else None))


@asynccontextmanager
async def actual_s2_ingress(owner, subject, output):
    """Give the real client its own loop, as the normal client/owner processes do.

    The production spawn fence holds the wire lock until its UI-loop subprocess
    launch completes. Co-locating a synchronous backend observer on that loop
    creates a fixture-only deadlock. Separate loop custody preserves both normal
    production paths and all original lock/identity admission rules.
    """
    ready = Future()

    async def serve():
        try:
            async with _open_actual_s2_ingress(owner, subject, output) as observer:
                close = asyncio.Event()
                ready.set_result((observer, asyncio.get_running_loop(), close))
                await close.wait()
        except BaseException as error:
            if not ready.done():
                ready.set_exception(error)
            raise

    # This is a test-owned application resource, not another semantic owner,
    # process registry or provider. The executor and application are joined.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='actual-s2-toad') as executor:
        finished = executor.submit(lambda: asyncio.run(serve()))
        observer = loop = close = None
        try:
            observer, loop, close = await asyncio.shield(asyncio.wrap_future(ready))
            yield IsolatedS2Ingress(observer, loop)
        finally:
            if loop is None:
                # Startup still owns the live application: acquire its original
                # resource before retirement rather than abandon the thread.
                observer, loop, close = await asyncio.shield(asyncio.wrap_future(ready))
            loop.call_soon_threadsafe(close.set)
            await asyncio.shield(asyncio.wrap_future(finished))
