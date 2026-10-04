"""Installed read-only saved App and decoded context labels; no model input."""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from functools import partial

from agent_comms.comms import Comms
from toad.app import ToadApp
from toad.core.context_inspection import ManifestNode, RecordedTurnNode
from toad.navigation_target import DirectTarget, NavigationContext
from toad.screens.historical_sessions import HistoricalSessions
from toad.widgets.context_explorer import ContextExplorer
from toad.widgets.transcript_history import TranscriptHistory
from textual.widgets import Tree, TextArea
from toad.widgets.side_bar import SideBar, SideBarCollapsible

async def until(pilot, predicate):
    async with asyncio.timeout(20):
        while not predicate():
            await pilot.pause(.03)

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

async def main():
    evidence=Path(os.environ['F4_APP_EVIDENCE'])
    fixture=Path(os.environ['F4_ANNOTATION_FIXTURE'])
    original=Path(os.environ['F4_SAVED_ORIGINAL'])
    root=fixture/'wire'
    source=Comms(original/'wire')
    thread=source.registry.require('configured-source')
    saved=Path(thread.session_file)
    protected=[original/'wire'/name for name in ('registry.json','bus.jsonl','input_dispositions.json','native_prompt_bindings.sqlite3','compaction-commits.sqlite3')]+[saved]
    before={str(p):digest(p) for p in protected}
    receipt={'state':'RUNNING','python':sys.executable,'root':str(root),'original_root':str(original/'wire'),
             'saved_session':str(saved),'protected_before':before,'provider_calls':0,'native_inputs':0,
             'public_inputs':0,'replayed_inputs':0,'film':False}
    started=time.monotonic()
    service=Comms(root)
    history=service.views.attach_history(original/'wire')
    me=service.messaging.user_identity(str(fixture)).name
    service.threads.restore_stopped(service.registry.snapshot(),tuple(service.registry.snapshot().threads))
    current_bus=digest(root/'bus.jsonl')
    os.environ.update(AGENT_COMMS_ROOT=str(root),XDG_CONFIG_HOME=str(evidence/'config'),
                     XDG_STATE_HOME=str(evidence/'state'),XDG_DATA_HOME=str(evidence/'data'))
    for key in ('AGENT_COMMS_THREAD','PI_AGENT_ID','PI_PROMPT','PYTHONPATH','AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID','AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE'):
        os.environ.pop(key,None)
    app=ToadApp(project_dir=str(fixture))
    try:
        async with app.run_test(size=(130,42),headless=False) as pilot:
            assert type(app._driver).__name__=='LinuxDriver'
            assert os.environ['DISPLAY']!=':0'
            await app.selected_session.wait_content_ready()
            original_mode=app.selected_mode
            default=app.selected_session
            receipt['driver']=type(app._driver).__name__
            receipt['default_source']=type(default).__name__
            # Selection uses the original explorer identity API, never a
            # fabricated native context or replacement producer/read method.
            explorer=default.query_one(ContextExplorer)
            explorer.set_identity('annotation-owner',str(root))
            panel=explorer.query_ancestor(SideBarCollapsible)
            sidebar=explorer.query_ancestor(SideBar)
            sidebar.reveal(); panel.collapsed=False
            explorer.action_refresh()
            tree=explorer.query_one(Tree)
            await until(pilot,lambda:any(isinstance(n.data,RecordedTurnNode) for n in explorer._context_nodes.values()))
            turn=next(n for n in explorer._context_nodes.values() if isinstance(n.data,RecordedTurnNode))
            tree.focus(); tree.select_node(turn)
            await pilot.press('space')
            await until(pilot,lambda:any(isinstance(n.data,ManifestNode) for n in explorer._context_nodes.values()))
            parent=next(n for n in explorer._context_nodes.values() if isinstance(n.data,ManifestNode))
            tree.focus(); tree.select_node(parent)
            await pilot.press('space')
            await until(pilot,lambda:any(isinstance(n.data,ManifestNode) and n.data.label.startswith('User Input') for n in explorer._context_nodes.values()))
            child=next(n for n in explorer._context_nodes.values() if isinstance(n.data,ManifestNode) and n.data.label.startswith('User Input'))
            tree.select_node(child); await pilot.pause(.1)
            await until(pilot,lambda:explorer.query_one(TextArea).text.startswith('User Input\n'))
            receipt['recorded_parent_label']=str(parent.label)
            receipt['recorded_child_label']=str(child.label)
            receipt['recorded_detail']=explorer.query_one(TextArea).text
            assert '<class' not in receipt['recorded_detail']
            app.save_screenshot('context-labels.svg',path=str(evidence))
            context=NavigationContext(app,original_mode,fixture,me)
            await DirectTarget('annotation-owner').open(context)
            await app.selected_session.wait_content_ready()
            history_mode=app.selected_mode
            assert history_mode!=original_mode
            await app.selected_session.action_historical_sessions()
            await until(pilot,lambda:isinstance(app.screen,HistoricalSessions))
            screen=app.screen
            await until(pilot,lambda:bool(screen.query(TranscriptHistory)))
            transcript=screen.query_one(TranscriptHistory)
            await until(pilot,lambda:bool(transcript.pages))
            receipt['saved_events']=sum(len(p.page.events) for p in transcript.pages)
            receipt['saved_cursor_file']=transcript.pages[-1].page.after.session_file
            assert receipt['saved_cursor_file']==str(saved)
            assert receipt['saved_events']>0
            await pilot.pause(.2)
            app.save_screenshot('original-saved-session.svg',path=str(evidence))
            await pilot.press('escape')
            await until(pilot,lambda:not isinstance(app.screen,HistoricalSessions))
            await app.session_navigation.close(history_mode)
            await app.select_session(original_mode)
            await pilot.pause(.1)
            assert app.selected_session is default
            assert app._exception is None
            receipt['closed_history_and_returned_original']=True
        receipt['whole_app_exit']=True
        assert app._exception is None
        receipt['protected_after']={str(p):digest(p) for p in protected}
        assert receipt['protected_after']==before
        assert digest(root/'bus.jsonl')==current_bus
        receipt['state']='PASS'
    except BaseException as exc:
        receipt['state']='FAILED';receipt['exception']=repr(exc)
        raise
    finally:
        receipt['seconds']=time.monotonic()-started
        (evidence/'terminal-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')

if __name__=='__main__':
    asyncio.run(main())
