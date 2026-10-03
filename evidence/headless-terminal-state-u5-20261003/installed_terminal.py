"""Original installed ACP terminal and native view, with no prompt/provider call."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
sys.path.insert(0,str(ROOT/'evidence/headless-agent-services-u2-20261003'))
from installed_services import InstalledApp
from l0a_native_installed_pilot import main, until
from native_terminal_retention_pilot import pty_masters
from native_session_retention_pilot import conversation_paint
from saved_state_user_journey_pilot import click_tab
from toad.acp.agent_controller import DetachedSurfaceBinding
from toad.terminal_execution import Command, TerminalExecution
from toad.widgets.terminal_tool import TerminalTool
from textual.geometry import Offset
from textual.selection import Selection

async def acceptance(app,pilot,agent,comms,entered,release,hold_next,requests):
    started=time.monotonic(); initial=pty_masters(); mode=app.selected_session.id
    original_process=agent.process.process
    configured=TerminalExecution(Command('sh',['-c','stty size; printf CONFIGURED_DETACHED'],dict(os.environ),str(app.project_dir)),width=57,height=13)
    try:
        DetachedSurfaceBinding().prepare_terminal(configured.state)
        await configured.start()
        await configured.wait_for_exit()
        configured_output,_=configured.get_output()
        assert configured_output.startswith('13 57'),configured_output
        assert (configured.state.width,configured.state.height)==(57,13)
    finally:
        await configured.close()
    request_id=0
    async def rpc(method,**params):
        nonlocal request_id
        request_id+=1
        response=await agent.server.call({'jsonrpc':'2.0','id':request_id,'method':method,'params':{'sessionId':agent.session_id,**params}})
        assert 'error' not in response,response
        return response['result']
    program="import sys\nfor i in range(1200): print('\\x1b[38;2;207;67;31mROW%04d 界 🙂 '%i+'wide '*25+'\\x1b[0m')\nprint('\\x1b[38;2;207;67;31mFINAL_NATIVE_CJK 界 🙂\\x1b[0m')"
    first=(await rpc('terminal/create',command=sys.executable,args=['-c',program]))['terminalId']
    execution=agent.controller.terminals.require(first); state=execution.state
    assert (await rpc('terminal/wait_for_exit',terminalId=first))['exitCode']==0
    assert 'FINAL_NATIVE_CJK 界 🙂' in (await rpc('terminal/output',terminalId=first))['output']
    assert len(state.scrollback_buffer.lines)>=1200
    await app.session_navigation.new(app.session_navigation.default_source)
    assert agent.controller.surface.target is None
    second=(await rpc('terminal/create',command='sh',args=['-c','stty size; printf DETACHED_NATIVE_TERMINAL']))['terminalId']
    detached=agent.controller.terminals.require(second)
    assert (await rpc('terminal/wait_for_exit',terminalId=second))['exitCode']==0
    detached_output=(await rpc('terminal/output',terminalId=second))['output']
    assert detached_output.startswith(f'{detached.state.DEFAULT_HEIGHT} {detached.state.DEFAULT_WIDTH}'),detached_output
    await click_tab(app,pilot,mode)
    await until(pilot,lambda: app.screen.query_one_optional(f'#{first}',TerminalTool) is not None)
    widget=app.screen.query_one(f'#{first}',TerminalTool)
    assert widget.state is state and agent.process.process is original_process
    assert widget.width==state.width and widget.height==state.height
    view=app.selected_session.conversation
    widget.scroll_end(animate=False,immediate=True)
    view.window.scroll_end(animate=False,immediate=True)
    await until(pilot,lambda:'FINAL_NATIVE_CJK' in conversation_paint(app.screen))
    frame=conversation_paint(app.screen)
    assert '界' in frame and '🙂' in frame,frame
    app.save_screenshot('native-terminal-model.svg',path=os.environ['L0A_EVIDENCE'])
    # Actual original selection is character-based on the unfolded model line.
    last_line=next(i for i,line in enumerate(state.buffer.lines) if 'FINAL_NATIVE_CJK' in line.content.plain)
    selection=Selection.from_offsets(Offset(0,last_line),Offset(len('FINAL_NATIVE_CJK'),last_line))
    assert widget.get_selection(selection)[0]=='FINAL_NATIVE_CJK'
    app.screen.selections={widget:selection}
    selected=widget._render_line(0,state.buffer.line_to_fold[last_line],state.width)
    assert 'FINAL_NATIVE_CJK' in selected.text
    assert any(segment.style is not None and segment.style.bgcolor is not None for segment in selected)
    app.screen.selections={}
    for terminal_id in (first,second): await rpc('terminal/release',terminalId=terminal_id)
    assert not agent.controller.terminals.executions and pty_masters()==initial
    assert requests==[],requests
    result={'result':'PASS','elapsed_seconds':time.monotonic()-started,'native_provider_requests':0,'configured_detached_geometry':[57,13],'configured_pty_output':configured_output,'detached_default_output':detached_output,'original_state_retained_after_reattach':True,'widget_geometry_derived_from_state':True,'large_native_stream_lines':1200,'unicode_color_paint_and_selection':True,'final_pty_masters_retained':False,'application':'Real installed Toad/ACP/Pi callbacks/native PTYs; Textual Pilot (not physical st recording)'}
    Path(os.environ['L0A_EVIDENCE'],'terminal-model-receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)

if __name__=='__main__':
    asyncio.run(main(app_type=InstalledApp,acceptance=acceptance,fixture_stage=os.environ['U5_FIXTURE_ROOT'],provider_request_budget=0))
