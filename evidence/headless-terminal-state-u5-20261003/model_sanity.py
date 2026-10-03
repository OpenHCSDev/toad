"""Affected installed ANSI/model contracts after the complete source migration."""
import asyncio,json,sys,time
from pathlib import Path
from toad.ansi import TerminalState
from toad.terminal_execution import TerminalExecution
assert not any(x=='textual' or x.startswith('textual.') for x in sys.modules),[x for x in sys.modules if x.startswith('textual')]
async def main():
    output=[]
    async def stdin(value): output.append(value)
    state=TerminalState(stdin,width=57,height=13)
    await state.write('hello\rX\x1b[31m红\x1b[0m\tEND\n')
    # Replace mode overwrites the old llo with the tab/END at cursor offset2.
    assert state.buffer.lines[0].content.plain=='X红\tEND',state.buffer.lines[0].content.plain
    assert state.buffer.lines[0].content.spans
    assert state.key_to_stdin('left',None)=='\x1b[D'
    await state.write('\x1b[?1h\x1b[?2004h')
    assert state.key_to_stdin('left',None)=='\x1bOD' and state.bracketed_paste
    await state.write('\x1b[3;5H\x1b[6n'); assert output[-1]=='\x1b[3;5R'
    state.update_size(height=19); assert(state.width,state.height)==(57,19)
    state.update_size(0,0); assert(state.width,state.height)==(57,19)
    stream=TerminalState(stdin,width=73,height=13)
    text=''.join(f'\x1b[38;2;207;67;31mROW{i:04d} 界 🙂 '+('wide '*25)+'\x1b[0m\n' for i in range(1200))
    started=time.monotonic(); cpu=time.process_time()
    for start in range(0,len(text),4096): await stream.write(text[start:start+4096])
    elapsed=time.monotonic()-started; cpu=time.process_time()-cpu
    assert 'ROW1199' in next(line.content.plain for line in reversed(stream.buffer.lines) if line.content.plain.strip())
    assert all(line.content.cell_len<=73 for line in stream.buffer.folded_lines)
    stream.update_size(91,21); assert all(line.content.cell_len<=91 for line in stream.buffer.folded_lines)
    await stream.write('\x1b[?1049hALT\x1b[?1049l')
    assert not stream.alternate_screen and 'ROW1199' in next(line.content.plain for line in reversed(stream.scrollback_buffer.lines) if line.content.plain.strip())
    r={'result':'PASS','scope':'Installed original model/execution imports no Textual; ANSI colors/unicode/cursor/modes/key/reply/geometry; bounded incremental stream and reflow. No application/provider yet.','stream_bytes':len(text.encode()),'stream_lines':1200,'elapsed_seconds':elapsed,'cpu_seconds':cpu,'model_width':stream.width,'model_height':stream.height,'folded_lines':len(stream.scrollback_buffer.folded_lines)}
    Path('evidence/headless-terminal-state-u5-20261003/model-sanity.json').write_text(json.dumps(r,indent=2)+'\n'); print(json.dumps(r))
asyncio.run(main())
