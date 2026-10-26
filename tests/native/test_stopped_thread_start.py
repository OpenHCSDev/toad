"""A stopped saved tab starts in place, then receives a real native DM reply."""
import asyncio
from dataclasses import replace

from agent_comms.channel_targets import CommandTarget, ThreadTarget
from agent_comms.cli_verbs.start import StartCliCommand
from agent_comms.pi_vocabulary import OffThinkingLevel
from agent_comms.session_file import RegistrySessionLocation
from support.journals import assistant_entry, write_journal
from support.native import ControlledProvider, MODEL, comms_agent, configure_provider
from toad.agent import AgentBase
from toad.session_scope import AgentAttached
from toad.target_commands import TargetContext
from toad.thread_actions import ThreadAction


async def test_start_attaches_stopped_saved_tab_and_receives_dm(workspace, native_package):
    comms = workspace.comms
    thread = workspace.thread('stopped')
    saved = workspace.roots.attempt / 'saved'
    saved.mkdir(mode=0o700)
    journal = write_journal(saved / 'saved.jsonl',
                            assistant_entry('SAVED_BEFORE_START', id='answer'))
    journal.chmod(0o600)
    comms.registry.declare(replace(thread, model=MODEL, thinking_level=OffThinkingLevel,
        session_file=RegistrySessionLocation.from_path(journal, comms.root)))
    provider = ControlledProvider()
    with provider.serving() as endpoint:
        configure_provider(endpoint)
        try:
            async with workspace.app(binding=AgentAttached(comms_agent()), resume='stopped') as ui:
                app, _ = ui.textual
                view, tab = ui.conversation, ui.selected_tab
                await ui.until_shows('SAVED_BEFORE_START')
                assert not comms.registry.require('stopped').process_alive
                ctx = TargetContext(app, comms, CommandTarget.named('stopped'),
                                    workspace.viewer, workspace.project, mode=tab)
                definition = next(action for action in ctx.available_actions()
                                  if action.declaration is StartCliCommand)
                ThreadAction.collect(ctx, definition)
                await ui.until(lambda: isinstance(view.agent_binding, AgentBase)
                               and view.agent_binding.ready, seconds=45,
                               why='Start to attach the saved tab')
                assert ui.conversation is view
                assert view.agent_binding.session_id == 'stopped'
                assert not provider.requests, 'Start must not submit a prompt'
                before = comms.registry.require('stopped').process_identity
                # A second successful Start must still nominate this tab for attachment.
                result = await asyncio.to_thread(comms.owners.start, 'stopped')
                assert not result.launched
                assert result.reconnect_targets() == ('stopped',)
                assert comms.registry.require('stopped').process_identity == before
                await asyncio.to_thread(comms.messaging.send_user_message, ThreadTarget('stopped'),
                                        'Reply with a short test answer.', worktree=str(workspace.project))
                await ui.until_shows('NATIVE_RESPONSE_1', seconds=45)
                other = await ui.new_session()
                assert other != tab
                await ui.select_tab(tab)
                await ui.until_shows('NATIVE_RESPONSE_1')
                assert ui.conversation is view
                assert not provider.failures
        finally:
            await asyncio.to_thread(comms.owners.stop, 'stopped')
