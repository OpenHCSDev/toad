"""Read original saved SDK history and typed context in the installed App.

The original stopped private incarnation is attached through its producer. No
fork, provider request, prompt, history rewrite or uncertain-input replay.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import time
import traceback
from agent_comms.acp import CommsAgent
from agent_comms.active_route import read_active_route
from agent_comms.comms import Comms
from agent_comms.field_codec import FieldCodec
from agent_comms.input_disposition import InputDispositions
from agent_comms.owner_launch import RetainedOwnerLaunch
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.core.context_inspection import ManifestNode, NativeSegmentNode, RecordedTurnNode
from toad.widgets.context_explorer import ContextExplorer
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SideBarToggle
from textual.widgets import Tree, TextArea

def retain_exception(kind,value,trace):
    Path(os.environ['F4_APP_EVIDENCE']).joinpath('exception.txt').write_text(''.join(traceback.format_exception(kind,value,trace)))
    sys.__excepthook__(kind,value,trace)
sys.excepthook=retain_exception

async def until(pilot,predicate):
    async with asyncio.timeout(25):
        while not predicate():
            await pilot.pause(.03)

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

async def main():
    evidence=Path(os.environ['F4_APP_EVIDENCE']); original=Path(os.environ['F4_SAVED_ORIGINAL'])
    root=original/'wire';service=Comms(root);previous=service.registry.require('configured-source')
    assert not previous.require_process().alive()
    previous.require_idle()
    saved=Path(previous.require_saved_session())
    protected=[root/name for name in ('bus.jsonl','input_dispositions.json','native_prompt_bindings.sqlite3','compaction-commits.sqlite3')]+[saved]
    before={str(p):digest(p) for p in protected}
    inputs=InputDispositions(root/InputDispositions.filename).read()
    public=Comms(read_active_route().root); snapshot=public.registry.snapshot()
    selected=snapshot.require('openhcs-audit-merged-runtime')
    assert selected.model==previous.model and selected.thinking_level==previous.thinking_level
    retained=RetainedOwnerLaunch.capture(selected,snapshot)
    package=Path('/home/ts/wt/comms-task-aware-native-bundle-20261002/stack/.pi-native-086d511f2026b10d/node_modules/@earendil-works/pi-coding-agent')
    runtime=Path(sys.executable).parent
    with service.bus.log.locked():root_id=service.bus.log.read_metadata_unlocked().root_id
    env=dict(retained.environment)
    env.update(AGENT_COMMS_ROOT=str(root),AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
        AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),AGENT_COMMS_AGENT_BIN=str(runtime/'pi-comms-native'),
        AGENT_COMMS_RUNTIME_ROOT=str(runtime),PATH=str(runtime)+os.pathsep+env.get('PATH',os.defpath),
        XDG_CONFIG_HOME=str(original/'config'),XDG_STATE_HOME=str(evidence/'state'),XDG_DATA_HOME=str(evidence/'data'),
        F4_APP_EVIDENCE=str(evidence),DISPLAY=os.environ['DISPLAY'])
    for key in ('PYTHONPATH','PI_PROMPT','PI_AGENT_ID','PI_PARENT_ID','PI_TASK','AGENT_COMMS_THREAD','AGENT_COMMS_STARTUP_INPUT_KEY','NO_COLOR'):
        env.pop(key,None)
    os.environ.clear();os.environ.update(env)
    started=time.monotonic();owner=None;child=None
    receipt={'state':'RUNNING','python':sys.executable,'root':str(root),'saved_session':str(saved),
        'protected_before':before,'original_incarnation':FieldCodec.encode(previous.incarnation),
        'model':previous.model,'thinking':FieldCodec.encode(previous.thinking_level),
        'provider_calls':0,'native_inputs':0,'public_inputs':0,'replayed_inputs':0,'film':False}
    try:
        service.threads.restore_stopped(service.registry.snapshot(),(previous.name,))
        owner=CommsAgent(service,private_nk_native_package=package,private_nk_wire_root_id=root_id,
            agent_bin=str(runtime/'pi-comms-native'),agent_args=list(retained.arguments or ()),auto_wake=False,runtime_enabled=True)
        service.owners.pin_private_nk_launch(root,root_id,package)
        declared=service.owners.acquire_thread(previous.name,owner_pid=os.getpid())
        assert declared.incarnation==previous.incarnation
        await owner._runtime.start();await owner.sessions.bind_owned(declared,declared.name)
        receipt['controller']=FieldCodec.encode(declared.require_process())
        definition=AgentDefinition.decode({'name':'F4 saved source','identity':'agent-comms.openhcs.dev','short_name':'comms','protocol':'acp',
            'run_command':{'*':shlex.join((sys.executable,'-m','agent_comms.acp'))}})
        app=ToadApp(agent_data=definition,project_dir=declared.worktree,agent_session_id=declared.name)
        async with app.run_test(size=(130,42),headless=False) as pilot:
            assert type(app._driver).__name__=='LinuxDriver' and os.environ['DISPLAY']!=':0'
            await app.selected_session.wait_content_ready()
            source=app.selected_session
            await until(pilot,lambda:bool(source.conversation.contents.query(TranscriptHistory)))
            history=source.conversation.contents.query_one(TranscriptHistory)
            await until(pilot,lambda:bool(history.pages))
            receipt['driver']=type(app._driver).__name__;receipt['default_source']=type(source).__name__
            receipt['saved_events']=sum(len(p.page.events) for p in history.pages)
            receipt['saved_cursor_file']=history.pages[-1].page.after.session_file
            assert receipt['saved_cursor_file']==str(saved) and receipt['saved_events']>0
            app.save_screenshot('original-saved-session.svg',path=str(evidence))
            sidebar,=(bar for bar in source.query(SideBar) if bar.right)
            assert await pilot.click(sidebar.query_one(SideBarToggle))
            await sidebar.wait_content_ready()
            explorer=source.query_one(ContextExplorer)
            explorer.query_ancestor(SideBarCollapsible).collapsed=False
            explorer.action_refresh()
            await until(pilot,lambda:explorer._native is not None)
            receipt['native_contributors']=len(explorer._native.contributors)
            assert receipt['native_contributors']>0
            tree=explorer.query_one(Tree)
            # Current contributor nodes and sealed recorded nodes are both
            # constructed by the original explorer; the node owner supplies labels.
            current_nodes=[n for n in explorer._context_nodes.values() if isinstance(n.data,NativeSegmentNode)]
            receipt['current_native_labels']=[n.data.label for n in current_nodes]
            # Supplied Core contributors have no nested measured manifests.
            # Read that declared contract instead of inventing a nested child.
            measured=[n for n in current_nodes if n.data.segment.contributor_manifests()]
            for current in measured:
                tree.focus();tree.move_cursor(current);await pilot.press('space')
            await pilot.pause(.1)
            current_children=[n.data for n in explorer._context_nodes.values() if isinstance(n.data,ManifestNode)]
            for node in current_children:
                assert node.label==node.segment.public_description()
                assert node.detail().startswith(node.segment.kind.public_title()+'\n')
            receipt['current_nested_manifest_labels']=[n.label for n in current_children]
            recorded=next(n for n in explorer._context_nodes.values() if isinstance(n.data,RecordedTurnNode))
            recorded.parent.expand();await pilot.pause()
            tree.move_cursor(recorded);await pilot.press('space')
            parent=next(n for n in explorer._context_nodes.values() if isinstance(n.data,ManifestNode) and n.parent is recorded)
            tree.move_cursor(parent);await pilot.press('space');await pilot.pause(.1)
            manifest_nodes=[n.data for n in explorer._context_nodes.values() if isinstance(n.data,ManifestNode)]
            for node in manifest_nodes:
                assert node.label==node.segment.public_description()
                assert node.detail().startswith(node.segment.kind.public_title()+'\n')
            tree.move_cursor(parent);await pilot.pause()
            assert tree.cursor_node is parent
            await until(pilot,lambda:explorer.query_one(TextArea).text.startswith(parent.data.segment.kind.public_title()+'\n'))
            receipt['recorded_labels']=[n.label for n in manifest_nodes]
            app.save_screenshot('context-labels.svg',path=str(evidence))
            capture=await asyncio.create_subprocess_exec('import','-display',os.environ['DISPLAY'],'-window','root',str(evidence/'context-labels.png'))
            assert await capture.wait()==0
            for backend in owner.turns.persistent_backends.values():
                if backend.custody.retained:child=backend.custody.idle().child
            assert child is not None
            receipt['native_process']=FieldCodec.encode(child.proc.identity)
            assert app._exception is None
        receipt['whole_app_exit']=True;assert app._exception is None
        receipt['state']='PASS'
    except BaseException as exc:
        receipt['state']='FAILED';receipt['exception']=repr(exc);raise
    finally:
        if owner is not None:
            for backend in owner.turns.persistent_backends.values():
                if backend.custody.retained:
                    child=backend.custody.idle().child
                    receipt['native_process']=FieldCodec.encode(child.proc.identity)
            await owner.shutdown()
        if child is not None:receipt['native_child_retired']=child.proc.retired and not child.proc.alive()
        receipt['protected_after']={str(p):digest(p) for p in protected}
        receipt['protected_unchanged']=receipt['protected_after']==before
        receipt['original_inputs_unchanged']=InputDispositions(root/InputDispositions.filename).read()==inputs
        if 'explorer' in locals():
            receipt['visible_detail_at_exit']=explorer.query_one(TextArea).text if explorer.is_attached else 'Original explorer retired'
        receipt['after_incarnation']=FieldCodec.encode(service.registry.require(previous.name).incarnation)
        receipt['seconds']=time.monotonic()-started
        (evidence/'terminal-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        assert receipt['protected_unchanged'] and receipt['original_inputs_unchanged']

if __name__=='__main__':asyncio.run(main())
