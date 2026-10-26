"""Opening saved history is not Start; Start attaches the original session."""
from dataclasses import replace

from agent_comms.session_file import RegistrySessionLocation
from support.native import comms_agent
from support.journals import assistant_entry, write_journal
from toad.session_scope import AgentAttached


async def test_opening_stopped_thread_reads_history_without_loading_an_agent(workspace):
    thread = workspace.thread('stopped')
    journal = write_journal(workspace.project / 'saved.jsonl',
                            assistant_entry('SAVED_STOPPED_ANSWER', id='answer'))
    workspace.comms.registry.declare(replace(thread, session_file=
        RegistrySessionLocation.from_path(journal, workspace.comms.root)))
    async with workspace.app(binding=AgentAttached(comms_agent()), resume='stopped') as ui:
        await ui.until_shows('SAVED_STOPPED_ANSWER')
        assert not workspace.comms.registry.require('stopped').process_alive
        assert not ui.conversation.agent_binding.ready
        assert not workspace.child_processes('agent_comms.acp')


async def test_started_owner_attaches_original_saved_session_in_place(workspace):
    from agent_comms.child_process import ProcessIdentity
    from agent_comms.route_selection import RouteSelection
    from support.agents import peer
    import os

    thread = workspace.thread('stopped')
    async with workspace.app(binding=AgentAttached(peer('load_existing')), resume='stopped') as ui:
        app, _ = ui.textual
        view, tab = ui.conversation, ui.selected_tab
        await ui.write_draft('KEEP_MY_DRAFT')
        # The controlled ACP process owns the protocol below. Publish a live
        # owner binding only after the stopped view has been opened.
        workspace.comms.registry.declare(replace(thread,
            process_identity=ProcessIdentity.capture(os.getpid())))
        await app.session_navigation.reconnect(
            RouteSelection.capture(workspace.comms.root), ('stopped',))
        await ui.until(lambda: {'loaded': 'stopped'} in workspace.received(),
                       why='ACP to load the original saved session')
        assert ui.conversation is view
        assert view.agent_binding.session_id == 'stopped'
        assert workspace.received() == [{'loaded': 'stopped'}]
        assert ui.draft() == 'KEEP_MY_DRAFT'
        other = await ui.new_session()
        assert other != tab
        await ui.select_tab(tab)
        assert ui.conversation is view
        assert view.agent_binding.session_id == 'stopped'
