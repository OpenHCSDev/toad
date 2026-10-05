"""Real saved native history through canonical hierarchy, menu, fork and reply.

Final idle rendering performance is independently owned by Tesla/Carver; the
original full saved journey, including its stricter idle assertion, is retained.
"""
import asyncio
from pathlib import Path

from l0a_native_installed_pilot import main as native_fixture, until, direct_reply_feedback
from native_session_retention_pilot import InstalledApp, conversation_paint
from runtime_fixture import wait_channel_roster
from saved_state_user_journey_pilot import (
    prepare_saved_state, click_tab, screen_paint, independent_source_publication,
    unopened_participant, clicked_reader_editor_return, fork_and_first_input,
    channel_reply_feedback,
)
from toad.screens.comms import CommsScreen
from toad.target_commands import ViewCommand
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.comms_sidebar import ChannelGroup


class DeclarationSidebarCommand(ViewCommand):
    help='Sidebar declaration proof'

    def available(self, ctx):
        return True

    def execute(self, ctx):
        (ctx.project/'sidebar-declaration-proof').write_text(ctx.subject)


async def acceptance(app,pilot,agent,comms,entered,release,hold_next,requests):
    first=app.selected_session
    await until(pilot,lambda:'NATIVE_RESPONSE_2' in conversation_paint(app.screen))
    assert 'SAVED_READER_1' in conversation_paint(app.screen)
    await independent_source_publication(agent,comms)
    sidebar=await wait_channel_roster(app,pilot,'#team')
    retained=sidebar.projection.channels['#team']
    group=retained.query_ancestor(ChannelGroup)
    retained.scroll_visible(animate=False,immediate=True);await pilot.pause()
    assert await pilot.click(retained,button=3)
    await until(pilot,lambda:any(item.action==DeclarationSidebarCommand.declared_name
                                for item in app.screen.query(ContextMenuItem)))
    command=next(item for item in app.screen.query(ContextMenuItem)
                 if item.action==DeclarationSidebarCommand.declared_name)
    assert await pilot.click(command)
    await until(pilot,lambda:(app.project_dir/'sidebar-declaration-proof').exists())
    await until(pilot,lambda:app.screen is app.workspace_screen and app.screen.frame_presentation.ready)
    assert (app.project_dir/'sidebar-declaration-proof').read_text()=='#team'
    print('DECLARATION_OWNED_NEW_MENU_COMMAND_PHYSICAL_CLICK_NO_CONSUMER_EDIT',flush=True)
    # Physical disclosure and keyboard traversal preserve one hierarchy identity.
    if group.expanded is False:
        assert await pilot.click(group.disclosure)
    await until(pilot,lambda:len(group.member_container.children)>=2)
    member=next(row for row in group.member_container.children if row.target_name=='beta')
    member.focus();await until(pilot,lambda:member.has_focus)
    await pilot.press('down','up')
    assert member.has_focus
    assert sidebar.navigation.state.expanded['#team']
    retained.scroll_visible(animate=False,immediate=True);await pilot.pause()
    assert await pilot.click(retained)
    await until(pilot,lambda:isinstance(app.selected_session,CommsScreen))
    channel=app.selected_session
    await until(pilot,lambda:'SAVED_CHANNEL_MESSAGE' in screen_paint(app))
    assert app.workspace_chrome.channels.widget.roster is sidebar
    assert sidebar.projection.channels['#team'] is retained
    await click_tab(app,pilot,first.id)
    await until(pilot,lambda:'NATIVE_RESPONSE_2' in conversation_paint(app.screen))
    assert len(requests)==2
    gamma=await unopened_participant(app,pilot,comms,channel,entered,release,hold_next,requests)
    await clicked_reader_editor_return(app,pilot,first)
    assert sidebar.projection.channels['#team'] is retained
    await fork_and_first_input(app,pilot,comms,first,entered,release,hold_next,requests)
    await channel_reply_feedback(app,pilot,comms,channel,first,entered,release,hold_next,requests,gamma)
    await direct_reply_feedback(pilot,app,comms,first.id,app.project_dir,entered,release,hold_next)
    assert sidebar.projection.channels['#team'] is retained
    assert app._exception is None
    print('SAVED_HIERARCHY_KEYBOARD_MENU_CHANNEL_PARTICIPANT_FORK_REPLY_RETURN_PASS',flush=True)


if __name__=='__main__':
    asyncio.run(native_fixture(app_type=InstalledApp,prepare_state=prepare_saved_state,acceptance=acceptance))
