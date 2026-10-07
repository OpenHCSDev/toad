"""Real private admissions, hidden retirement and selected prompt discovery."""
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import sys
from time import perf_counter

from agent_comms.comms import Comms
from agent_comms.registry_store import RegistryStore
from agent_comms.threads import Thread
from runtime_fixture import ToadApp
from toad.core.events import CoordinationObserved
from toad.screens.main import MainScreen
from toad.target_commands import TargetContext
from toad.widgets.conversation import Conversation
from textual.widgets import OptionList


async def main(output):
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    project = output / 'project'
    project.mkdir()
    for key in tuple(os.environ):
        if key.startswith('AGENT_COMMS_'):
            del os.environ[key]
    os.environ.update(AGENT_COMMS_ROOT=str(output / 'wire'),
        TOAD_TEST_ATTEMPT=str(output), XDG_CONFIG_HOME=str(output / 'config'),
        XDG_STATE_HOME=str(output / 'state'), XDG_DATA_HOME=str(output / 'data'),
        XDG_CACHE_HOME=str(output / 'cache'))
    service = Comms(output / 'wire', private_initial_writes=True)
    service.messaging.initialize_private_initial_protocol()
    owners = []
    for number in range(4):
        path = project if number == 0 else project / f'agent-{number}'
        path.mkdir(exist_ok=True)
        owners.append(service.registry.declare(Thread(
            'project' if number == 0 else f'agent-{number}', frozenset({'team'}), str(path))))
    app = ToadApp(project_dir=str(project))
    async with app.run_test(size=(140, 48)) as pilot:
        await app.selected_session.wait_content_ready()
        first = app.selected_session
        def source(owner):
            view = MainScreen(Path(owner.worktree))
            view.initial_coordination_root = str(service.root)
            return view
        modes = {}
        for owner in owners[1:]:
            details = await app.session_navigation.new(
                lambda owner=owner: source(owner), original=(str(service.root), owner.incarnation))
            modes[owner.name] = details.mode_name
        await app.select_session(first.id)
        await pilot.pause()
        # All original service/documents are acquired before measuring idle reads.
        await app.session_navigation.retire_missing()
        await pilot.pause()
        observed = app.coordination_access.observed_service
        calls = Counter()
        watched = {Comms.__init__.__code__: 'service_constructions',
            RegistryStore._decode.__code__: 'registry_decodes',
            TargetContext.available_actions.__code__: 'action_discovery',
            OptionList.set_options.__code__: 'option_rebuilds'}
        monitor = sys.monitoring
        monitor.use_tool_id(monitor.PROFILER_ID, 'private-navigation-lifetime')
        monitor.register_callback(monitor.PROFILER_ID, monitor.events.PY_START,
            lambda code, offset: calls.update((watched[code],)))
        for code in watched:
            monitor.set_local_events(monitor.PROFILER_ID, code, monitor.events.PY_START)
        start = perf_counter()
        try:
            for _ in range(4):
                await app.session_navigation.retire_missing()
                app.coordination_access.events.publish(CoordinationObserved())
                await pilot.pause()
            assert app.coordination_access.observed_service is observed
            assert calls['service_constructions'] == calls['registry_decodes'] == 0
            assert calls['action_discovery'] == calls['option_rebuilds'] == 0
            # Every hidden prompt remains a view, not a repeated backend query.
            idle = dict(calls)
            before = calls['action_discovery']
            hidden = app.workspace_sessions.views[modes['agent-1']]
            await hidden.query_one(Conversation).update_slash_commands().wait()
            assert calls['action_discovery'] == before
            await app.select_session(hidden.id)
            await hidden.query_one(Conversation).update_slash_commands().wait()
            assert calls['action_discovery'] > before
            selected_calls = dict(calls)
            conversation = hidden.query_one(Conversation)
            popup = conversation.prompt.slash_complete
            before = calls['option_rebuilds']
            conversation.prompt.slash_commands = list(conversation.prompt.slash_commands)
            await pilot.pause()
            assert calls['option_rebuilds'] == before
            conversation.prompt.focus()
            await pilot.press('/')
            await conversation.update_slash_commands().wait()
            await pilot.pause()
            assert popup.is_open and popup.option_list.option_count > 0
            assert calls['option_rebuilds'] > before
            await pilot.press('escape')
            await pilot.pause()
            assert not popup.is_open
            assert conversation.prompt.prompt_text_area.text == '/'
            (output / 'reached.json').write_text(json.dumps(dict(idle=idle,
                completion_opened=True, closed_rows_skipped=True), indent=2) + '\n')
        finally:
            for code in watched:
                monitor.set_local_events(monitor.PROFILER_ID, code, 0)
            monitor.free_tool_id(monitor.PROFILER_ID)
        elapsed = perf_counter() - start
        # Rename preserves the admitted birth through canonical alias resolution.
        # Mounted source publication supersedes its initial admission hint.
        _, renamed_identity = app.session_navigation.get(modes['agent-2']).original_threads(app.session_navigation)[0]
        service.registry.rename(renamed_identity.name, 'renamed-agent')
        await app.session_navigation.retire_missing()
        assert app.session_navigation.get(modes['agent-2']) is not None
        # A same-name successor cannot stand in for the original hidden source.
        _, original_identity = app.session_navigation.get(modes['agent-3']).original_threads(app.session_navigation)[0]
        old = service.registry.require(original_identity.name)
        service.registry.unregister(old.name)
        service.registry.delete_originals((service.registry.require(old.name),))
        service.registry.declare(Thread(old.name, old.tags, old.worktree,
                                       created_at=old.created_at + 1))
        await app.session_navigation.retire_missing()
        assert app.session_navigation.get(modes['agent-3']) is None
        # An unavailable/changed route supplies no evidence of deletion.
        other = Comms(output / 'other', private_initial_writes=True)
        other.messaging.initialize_private_initial_protocol()
        os.environ['AGENT_COMMS_ROOT'] = str(other.root)
        try:
            await app.session_navigation.retire_missing()
            assert app.session_navigation.get(modes['agent-2']) is not None
        finally:
            os.environ['AGENT_COMMS_ROOT'] = str(service.root)
        assert app._exception is None
        result = dict(admitted_native_views=4, repeated_idle_retirements=4,
            idle_owner_calls=idle, selected_owner_calls=selected_calls,
            completion_opened=True, closed_rows_skipped=True,
            idle_and_switch_seconds=elapsed,
            hidden_prompt_query_skipped=True, selected_prompt_reacquired=True,
            renamed_birth_retained=True, same_name_successor_retired=True,
            unavailable_route_retains_hidden=True,
            strength='private source headless App; no live tree-toggle or terminal claim')
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    asyncio.run(main(Path(sys.argv[1])))
