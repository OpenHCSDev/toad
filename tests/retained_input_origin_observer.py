"""Actual Toad ingress observer on the existing S2/S5 native private fixture.

The caller retains custody of its original RuntimeServer, native session and
provider. This helper opens the normal ACP client and Toad application on that
same root. It declares no new owner and never manufactures an author witness.
"""

import asyncio
import base64
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
        terminal = InputDispositions(inputs.path).read().lookup(key)
        assert terminal.origin == origin
        assert isinstance(terminal.origin.retained_fact(terminal), HumanInputTaskFact)
        source = Path(self.comms.registry.require(self.subject.name).require_saved_session())
        with NativeEntry.open_evidence(source) as reader:
            header, entries = reader.observe()
        user, = [entry for entry in entries if entry.input_id == terminal.native_id]
        assert user.message.user
        replies = []
        for entry in entries[entries.index(user) + 1:]:
            if entry.input_boundary:
                break
            if entry.final_reply:
                replies.append(entry)
        assert replies, 'Original tracked native input has no successful terminal reply'
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
            'actual_frame_body_occurrences': visible_occurrences,
            'frame_identity_limit': 'Equal bodies are not message identity; original native IDs are recorded separately.',
            'retained_fact': FieldCodec.encode(terminal.origin.retained_fact(terminal)),
        })
        self.persist('original_native_ids_terminal_reply_and_actual_frame')
        return terminal


@asynccontextmanager
async def actual_s2_ingress(owner, subject, output):
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
    try:
        definition = AgentDefinition.decode({
            'name': 'Original S2/S5 fixture', 'identity': 'original-s2-s5',
            'short_name': 's2-s5', 'protocol': 'acp',
            'run_command': {'*': shlex.join([sys.executable, '-m', 'agent_comms.acp'])},
        })
        app = ToadApp(agent_data=definition, project_dir=subject.worktree,
                      agent_session_id=subject.name)
        async with app.run_test(headless=True, size=(160, 44)) as pilot:
            await until(pilot, lambda: app.selected_session is not None)
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            await until(pilot, lambda: view.agent is not None)
            await until(pilot, view.agent.session.settled.is_set)
            assert view.agent.session.connected
            await until(pilot, lambda: view.agent.queue_attachment.scope is not None)
            observer = ActualS2Ingress(app, pilot, owner._comms, subject, output)
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
