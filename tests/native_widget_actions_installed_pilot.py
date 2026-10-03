"""One installed native saved-session journey through dynamic widget actions."""
import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path

from acp import schema
from textual.binding import Binding
from toad.answer import Answer
from toad.application_actions import KeyboundAction
from toad.question_actions import QuestionAction
from toad.screens.permissions import PermissionsScreen
from toad.widgets.question import Question, Option
from toad.widgets.coordination_context import CoordinationContext
from toad.widgets.flash import Flash
from runtime_fixture import ToadApp
from l0a_native_installed_pilot import main, until, response_painted


class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')

    async def on_load(self):
        from toad.native_themes import ThemeChoice
        self.settings.ui.theme = ThemeChoice.decode('textual-dark')
        await super().on_load()


def frame(app):
    return '\n'.join(strip.text for strip in app.screen._compositor.render_strips())


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    root = Path(os.environ['L0A_EVIDENCE'])
    view = app.selected_session.conversation
    release.set(); hold_next.clear()
    await until(pilot, lambda: view.agent_ready)
    view.prompt.text = 'ACTION_NATIVE_SAVED_HISTORY_' + root.name
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_1'), 30)
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    assert len(requests) == 1
    original = comms.registry.require('beta').process_identity
    await agent.session.reconnect()
    await until(pilot, agent.session.settled.is_set)
    await until(pilot, lambda: view.agent_ready and response_painted(app, view, 'NATIVE_RESPONSE_1'))
    assert len(requests) == 1 and comms.registry.require('beta').process_identity == original
    view.prompt.text = 'KEEP_ACTION_DRAFT'
    document = view.prompt.prompt_text_area.document
    history = view.prompt.prompt_text_area.history
    assert view.check_action('cancel', ()) is None
    assert view.check_action('focus_terminal', ()) is None
    assert view.check_action('mode_switcher', ()) is False
    await pilot.press('escape')
    assert not comms.registry.require('beta').executing

    disclosure = await view.post(CoordinationContext('ACTION_CONTEXT_VISIBLE'))
    await pilot.pause()
    # Native block-cursor key establishes the real history focus owner.
    view.focus_prompt(scroll_end=False)
    await pilot.press('alt+up')
    await until(pilot, lambda: app.screen.focused is view.window)
    assert view.cursor_block is disclosure and disclosure.collapsed
    assert view.check_action('expand_block', ()) is True
    await pilot.press('space')
    await until(pilot, lambda: not disclosure.collapsed and 'ACTION_CONTEXT_VISIBLE' in frame(app))
    assert view.check_action('collapse_block', ()) is True
    app.save_screenshot(str(root/'block-expanded.svg'))
    await pilot.press('space')
    await until(pilot, lambda: disclosure.collapsed)

    selected=[]
    view.ask([Answer('Allow native choice','original-allow',kind='allow_once'),
              Answer('Reject native choice','original-reject',kind='reject_once')],
             'DECLARED_QUESTION',callback=selected.append)
    question=view.prompt.query_one(Question)
    await until(pilot, lambda: len(question.query(Option))==2 and 'DECLARED_QUESTION' in frame(app))
    question.focus()
    await pilot.press('down')
    assert question.selection==1
    assert await pilot.click(question.query(Option)[0].query_one('#label'),offset=(1,0))
    assert question.selection==0
    assert question.check_action('select_kind',('allow_always',)) is False
    app.save_screenshot(str(root/'question-options.svg'))
    await pilot.press('A')
    assert not selected
    await pilot.press('enter','enter')
    assert [answer.id for answer in selected]==['original-allow']
    assert question.check_action('select',()) is False
    assert question.check_action('selection_down',()) is False
    await until(pilot,lambda:view.prompt._ask is None)

    # Feed an external request to the existing actual client controller; no mock UI,
    # backend/state copy or synthetic turn. Actual tool content opens native modal.
    result=asyncio.create_task(agent.permissions.request_permission(
        sessionId=agent.session_id,
        options=[schema.PermissionOption(option_id='modal-allow',name='Allow actual preview',kind='allow_once')],
        toolCall=schema.ToolCallUpdate(tool_call_id='action-preview',kind='edit',title='Actual preview',
            content=[schema.FileEditToolCallContent(type='diff',path=str(Path(view.working_directory)/'action.txt'),old_text='before',new_text='after')])))
    try:
        await until(pilot,lambda:isinstance(app.screen,PermissionsScreen))
        screen=app.screen
        await until(pilot,lambda:'Allow actual preview' in frame(app))
        assert screen.check_action('select_kind',('reject_once',)) is False
        app.save_screenshot(str(root/'permission-preview.svg'))
        await pilot.press('r')
        assert not result.done()
        # Screen priority action forwards availability and selection to the exact Question.
        assert await pilot.click(screen.navigator,offset=(1,0))
        await pilot.press('a')
        answer=await asyncio.wait_for(result,8)
        assert answer.outcome.option_id=='modal-allow'
        await until(pilot,lambda:not isinstance(app.screen,PermissionsScreen))
    finally:
        if not result.done():
            agent.permissions.cancel()
            await result

    # A new declaration supplies native binding, availability and effect without
    # editing dispatch, the action roster or the widget's action methods.
    class ReviewAction(KeyboundAction, QuestionAction):
        key='f8';description='Review'
        def available(self, question):
            return question.accepts_selection
        async def apply(self, question):
            question.title='DECLARATION_ONLY_REVIEW'
    class ReviewQuestion(Question):
        ACTIONS=QuestionAction
    probe=ReviewQuestion('New case',options=[Answer('New option','new-id')])
    await view.mount(probe)
    probe.focus()
    await pilot.press('f8')
    assert probe.title=='DECLARATION_ONLY_REVIEW'
    await probe.remove()

    view.focus_prompt(scroll_end=False)
    assert view.prompt.text=='KEEP_ACTION_DRAFT'
    assert view.prompt.prompt_text_area.document is document
    assert view.prompt.prompt_text_area.history is history
    assert len(requests)==1
    # Actual native held turn and physical double Escape, replacing SlowCancelAgent.
    entered.clear();release.clear();hold_next.set()
    view.prompt.text='ACTION_NEW_CANCEL_INPUT'
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot,entered.is_set)
    await until(pilot,lambda:view.turns.owner.busy)
    assert view.check_action('cancel',()) is True
    await pilot.press('escape')
    assert view.turns.owner.busy
    assert 'again' in str(view.query_one(Flash).render()).lower()
    app.save_screenshot(str(root/'cancel-first-escape.svg'))
    await pilot.press('escape')
    await until(pilot,lambda:not comms.registry.require('beta').executing,15)
    release.set()
    assert len(requests)==2
    assert not agent.permissions.pending
    assert app._exception is None
    (root/'action-receipt.json').write_text(json.dumps({
        'provider':'localhost-only','native_requests':len(requests),'paid_calls':0,
        'saved_native_reconnect_no_replay':True,'block_space_expand_collapse':True,
        'question_actual_pointer_keyboard_once':True,'permission_modal_forwarding':True,
        'declaration_only_new_case':True,'draft_document_history_identity':True,
        'actual_native_two_escape_cancel':True,
        'permission_request_source':'controlled actual PermissionController API; not provider-issued permission',
        'toad':__import__('toad').__file__,'core':__import__('agent_comms').__file__,
        'textual':__import__('textual').__file__},indent=2)+'\n')


if __name__=='__main__':
    asyncio.run(asyncio.wait_for(main(app_type=InstalledApp,acceptance=acceptance,
                     expected_response_disconnects=frozenset({2}),provider_request_budget=2,
                     fixture_stage=os.environ['ACTION_FIXTURE_STAGE']),115))
