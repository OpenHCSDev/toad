"""Explicitly authorized real-provider journey over native-forked retained history.

The public registration and source are read only. Original process credentials
stay in RAM; the native SessionManager owns two new private journal forks.
All new wire records, owners and inputs belong to the isolated fixture.
"""
import asyncio
import cProfile
import json
import os
import shlex
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.field_codec import FieldCodec
from agent_comms.native_fork import ForkSessionHelper, ForkSessionRequest
from agent_comms.native_package import verify_native_package
from agent_comms.owner_launch import RetainedOwnerLaunch
from agent_comms.registration import Registration
from agent_comms.threads import Thread
from agent_comms.transcript_events import TextTranscript
from toad.agent_schema import AgentDefinition
from toad.navigation_target import NavigationContext, channel_target, ThreadTarget
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.outgoing_message import OutgoingMessage
from toad.widgets.message_notifications import MessageNotifications
from toad.widgets.session_tabs import SessionLabel
from canonical_wire_conversation_installed_pilot import WindowApp, originals, original_native_reply_proof
from l0a_native_installed_pilot import until
from runtime_fixture import stop_test_children


async def main():
    assert os.environ['AC_REAL_PROVIDER_AUTHORIZED'] == 'Sol/high retained acceptance'
    evidence = Path(os.environ['L0A_EVIDENCE'])
    stage = Path(os.environ['AC_REAL_FIXTURE_STAGE'])
    assert stage.is_relative_to('/home/ts/wt')
    stage.mkdir(parents=True, exist_ok=False)
    evidence.mkdir(parents=True, exist_ok=True)
    source_root = Path(os.environ['AC_REAL_SOURCE_ROOT'])
    snapshot = Registration(source_root / 'registry.json').snapshot()
    source = snapshot.require_active(os.environ['AC_REAL_SOURCE_OWNER'])
    retained = RetainedOwnerLaunch.capture(source, snapshot)
    assert source.model is not None and 'sol' in source.model.lower()
    assert source.thinking_level.declared_name == 'high'
    source_file = Path(os.environ.get('AC_REAL_SOURCE_FILE', source.session_file))
    assert source_file.stat().st_size >= 40_000_000
    package = Path(os.environ['AC_NATIVE_COPIED_PACKAGE'])
    verify_native_package(package)
    project = stage / 'project'
    project.mkdir()
    helper_env = dict(retained.environment, PI_CODING_AGENT_DIR=str(stage / 'native-forks'))
    identities = [await ForkSessionHelper.run(
        ForkSessionRequest(str(package), str(source_file), str(project)),
        cwd=project, env=helper_env,
    ) for _ in range(2)]
    assert all(Path(identity.session_file).is_relative_to(stage) for identity in identities)
    profile = cProfile.Profile()
    with tempfile.TemporaryDirectory(prefix='comms-real-wire-', dir='/var/tmp') as directory:
        service = Comms(Path(directory) / 'wire')
        root_id = service.messaging.initialize_private_initial_protocol()
        service.owners.pin_private_nk_launch(service.root, root_id, package)
        # Preserve the selected provider, arguments, auth and settings. Only
        # the reviewed runtime and fixture-owned routing/UI resources change.
        runtime_path = str(Path(sys.executable).parent)
        environment = dict(retained.environment)
        environment.update(
            AGENT_COMMS_ROOT=str(service.root),
            AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
            AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),
            AGENT_COMMS_AGENT_BIN=str(Path(sys.executable).with_name('pi-comms-native')),
            AGENT_COMMS_AGENT_ARGS=shlex.join(retained.arguments or ()),
            PATH=runtime_path + os.pathsep + environment.get('PATH', ''),
            VIRTUAL_ENV=str(Path(sys.executable).parent.parent),
            AGENT_COMMS_RUNTIME_ROOT=runtime_path,
            XDG_CONFIG_HOME=str(stage / 'config'),
            XDG_STATE_HOME=str(stage / 'state'),
            XDG_DATA_HOME=str(stage / 'data'),
        )
        for name in ('PI_PROMPT', 'PI_PARENT_ID', 'PI_TASK', 'PI_AGENT_ID',
                     'AGENT_COMMS_THREAD', 'AGENT_COMMS_STARTUP_INPUT_KEY', 'PYTHONPATH'):
            environment.pop(name, None)
        os.environ.clear()
        os.environ.update(environment)
        os.environ['TOAD_TEST_ATTEMPT'] = stage.name
        for name, identity in zip(('alpha', 'beta'), identities, strict=True):
            service.registry.declare(Thread(
                name, frozenset({'team'}), str(project), session_file=identity.session_file,
                model=source.model, thinking_level=source.thinking_level,
                task='Bounded live acceptance only. Do not resume inherited work. '
                     'For acceptance messages answer exactly the requested token. No tools or goals.',
            ))
        definition = AgentDefinition.decode({
            'name': 'Real retained acceptance', 'identity': 'real-retained',
            'short_name': 'real', 'protocol': 'acp',
            'run_command': {'*': shlex.join([sys.executable, '-m', 'agent_comms.acp'])},
        })
        sender_app = WindowApp(agent_data=definition, project_dir=str(project), agent_session_id='alpha')
        receiver_app = WindowApp(agent_data=definition, project_dir=str(project), agent_session_id='beta')
        irc_app = WindowApp(project_dir=str(project))
        receipt = {'provider': source.model, 'thinking': source.thinking_level.declared_name,
                   'source_bytes': source_file.stat().st_size, 'original_inputs_replayed': 0}
        try:
            async with sender_app.run_test(size=(160, 44)) as sp, \
                       receiver_app.run_test(size=(160, 44)) as rp, \
                       irc_app.run_test(size=(160, 44)) as ip:
                sender, receiver = sender_app.selected_session.conversation, receiver_app.selected_session.conversation
                for view, pilot in ((sender, sp), (receiver, rp)):
                    await until(pilot, lambda: view.agent is not None and view.agent_ready, 50)
                    assert view.agent.session.connected
                user = service.messaging.user_identity(str(project)).name
                await channel_target('#team').open(NavigationContext(irc_app, irc_app.selected_mode, project, user))
                await irc_app.selected_session.wait_content_ready()
                irc = irc_app.selected_session.query_one(CommsChatView)
                await until(ip, lambda: irc.message_history.initialized)
                profile.enable()
                original = await asyncio.to_thread(service.messaging.send, 'alpha', '#team',
                    '@beta Bounded acceptance only. Do not resume prior work or use tools. '
                    'Reply exactly REAL_RETAINED_WIRE_REPLY to this channel message.')
                await until(sp, lambda: len(originals(sender, original.reference, OutgoingMessage)) == 1, 40)
                await until(rp, lambda: len(originals(receiver, original.reference, IncomingMessage)) == 1, 40)
                await until(ip, lambda: any(message.reference == original.reference for message, _ in irc.message_history.rows), 40)
                await until(rp, lambda: any(message.sender == 'beta' and 'REAL_RETAINED_WIRE_REPLY' in message.body
                                          for message in service.bus.log.full_history()), 60)
                reply = next(message for message in service.bus.log.full_history()
                             if message.sender == 'beta' and 'REAL_RETAINED_WIRE_REPLY' in message.body)
                await until(rp, lambda: len(originals(receiver, reply.reference, OutgoingMessage)) == 1, 30)
                await until(sp, lambda: len(originals(sender, reply.reference, IncomingMessage)) == 1, 30)
                receipt['original_native_reply'] = original_native_reply_proof(service, original, reply)
                for view, pilot, kind in ((sender, sp, OutgoingMessage), (receiver, rp, IncomingMessage)):
                    await until(pilot, lambda: 'Responded' in str(originals(view, original.reference, kind)[0]
                                                                .query_one(MessageNotifications).title), 30)
                # Same already-open views, beyond both reported 15–30s delays.
                timeline = []
                for second in range(31):
                    await rp.pause(1)
                    timeline.append({'second': second,
                        'original_sender': len(originals(sender, original.reference, OutgoingMessage)),
                        'original_receiver': len(originals(receiver, original.reference, IncomingMessage)),
                        'reply_receiver': len(originals(receiver, reply.reference, OutgoingMessage))})
                    assert all(value == 1 for key, value in timeline[-1].items() if key != 'second')
                    assert all(app._exception is None for app in (sender_app, receiver_app, irc_app))
                receipt['same_open_31s'] = timeline
                # Actual A/B/A clicks followed immediately by new bounded input.
                beta_screen = receiver_app.selected_session
                await ThreadTarget('alpha').open(NavigationContext(receiver_app, receiver_app.selected_mode, project, user))
                await receiver_app.selected_session.wait_content_ready()
                alpha_screen = receiver_app.selected_session
                timings = []
                for index, screen in enumerate((beta_screen, alpha_screen, beta_screen)):
                    label = next(label for label in receiver_app.screen.query(SessionLabel) if label.id == screen.id)
                    label.scroll_visible(animate=False, immediate=True)
                    await rp.pause()
                    began = time.monotonic()
                    assert await rp.click(label, offset=(label.size.width // 2, 0))
                    await until(rp, lambda: receiver_app.selected_session is screen)
                    token = f'REAL_RETAINED_RETURN_{index}'
                    view = screen.conversation
                    view.prompt.text = f'Bounded acceptance only; do not resume inherited work or use tools. Reply exactly {token}.'
                    view.prompt.prompt_text_area.focus()
                    await rp.press('enter')
                    await until(rp, lambda: service.registry.require(view.agent.session_id).last_finished_turn_id
                                and not service.registry.require(view.agent.session_id).executing
                                and any(isinstance(event, TextTranscript) and token in event.text
                                        for history in view.window.histories for event in history.coverage_events), 60)
                    timings.append({'thread': view.agent.session_id, 'reply_seconds': round(time.monotonic() - began, 3)})
                    assert len(originals(sender, original.reference, OutgoingMessage)) == 1
                    assert len(originals(receiver, original.reference, IncomingMessage)) == 1
                receipt['physical_return_immediate_send'] = timings
                cold_app = WindowApp(agent_data=definition, project_dir=str(project), agent_session_id='alpha')
                async with cold_app.run_test(size=(160, 44)) as cp:
                    cold = cold_app.selected_session.conversation
                    await until(cp, lambda: cold.agent is not None and cold.agent_ready, 40)
                    await until(cp, lambda: len(originals(cold, original.reference, OutgoingMessage)) == 1, 30)
                    await until(cp, lambda: len(originals(cold, reply.reference, IncomingMessage)) == 1, 30)
                    assert cold_app._exception is None
                receipt['cold_window_once'] = True
                receipt['original'] = FieldCodec.encode(original.reference)
                receipt['reply'] = FieldCodec.encode(reply.reference)
                for app, name in ((sender_app, 'sender'), (receiver_app, 'receiver'), (irc_app, 'irc')):
                    app.save_screenshot(str(evidence / f'{name}.svg'))
                receipt['complete'] = True
        except BaseException:
            import traceback
            (evidence / 'failure.txt').write_text(traceback.format_exc())
            raise
        finally:
            profile.disable()
            profile.dump_stats(str(evidence / 'actual-real-retained.prof'))
            (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2))
            # Never archive retained launch environment or auth/settings files.
            for thread in service.registry.all_threads().values():
                if thread.role.executable and thread.process_alive:
                    await asyncio.to_thread(service.owners.stop, thread.name)
            def nonresources(directory, names):
                return [name for name in names if not (stat.S_ISREG((Path(directory) / name).lstat().st_mode)
                                                       or stat.S_ISDIR((Path(directory) / name).lstat().st_mode))]
            shutil.copytree(service.root, evidence / 'original-private-wire', ignore=nonresources)
            await stop_test_children(stage.name)
            assert all(not thread.process_alive for thread in service.registry.all_threads().values())
    print('REAL_RETAINED_WIRE_ACCEPTANCE', json.dumps(receipt), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
