"""Official SDK peer exercises the real client's file/permission/terminal RPCs."""
import asyncio
import json
import sys

from acp import run_agent
from acp.schema import (AgentMessageChunk, EnvVariable, FileEditToolCallContent,
                        PermissionOption, TextContentBlock, ToolCallProgress,
                        ToolCallStart, ToolCallUpdate, PromptResponse, NewSessionResponse,
                        SessionMode, SessionModeState, SetSessionModeResponse, CurrentModeUpdate)
from acp_plan_server import PlanPeer


class SpecificationPeer(PlanPeer):
    async def new_session(self, cwd, **kwargs):
        response = await super().new_session(cwd, **kwargs)
        return NewSessionResponse(session_id=response.session_id, modes=SessionModeState(
            current_mode_id='read', available_modes=[SessionMode(id='read', name='SDK Read'),
                SessionMode(id='write', name='SDK Write')]))

    async def set_session_mode(self, session_id, mode_id, **kwargs):
        assert mode_id == 'write'
        await self.connection.session_update(session_id=session_id,
            update=CurrentModeUpdate(sessionUpdate='current_mode_update', current_mode_id=mode_id))
        return SetSessionModeResponse()

    async def prompt(self, session_id, prompt, **kwargs):
        assert prompt[0].text == 'SDK_SPECIFICATION_JOURNEY'
        path = str(self.project / 'sdk-file.txt')
        await self.connection.write_text_file(session_id=session_id, path=path, content='old SDK content')
        read = await self.connection.read_text_file(session_id=session_id, path=path)
        assert read.content == 'old SDK content'
        await self.connection.session_update(session_id=session_id, update=ToolCallStart(
            sessionUpdate='tool_call', tool_call_id='sdk-edit', title='SDK edit review',
            kind='edit', status='pending'))
        permission = await self.connection.request_permission(
            session_id=session_id,
            tool_call=ToolCallUpdate(tool_call_id='sdk-edit', title='SDK edit review', kind='edit',
                content=[FileEditToolCallContent(type='diff', path=path,
                    old_text=read.content, new_text='new SDK content')]),
            options=[PermissionOption(option_id='allow', name='Allow SDK edit', kind='allow_once')])
        assert permission.outcome.option_id == 'allow'
        await self.connection.write_text_file(session_id=session_id, path=path, content='new SDK content')
        await self.connection.session_update(session_id=session_id, update=ToolCallProgress(
            sessionUpdate='tool_call_update', tool_call_id='sdk-edit', status='in_progress'))
        created = await self.connection.create_terminal(session_id=session_id, command=sys.executable,
            args=['-c', 'import os; print(os.environ["SDK_VARIABLE"])'], cwd=str(self.project),
            env=[EnvVariable(name='SDK_VARIABLE', value='SDK_TERMINAL_PAINT')], output_byte_limit=1024)
        exited = await self.connection.wait_for_terminal_exit(session_id=session_id, terminal_id=created.terminal_id)
        assert exited.exit_code == 0 and exited.signal is None
        output = await self.connection.terminal_output(session_id=session_id, terminal_id=created.terminal_id)
        assert 'SDK_TERMINAL_PAINT' in output.output and not output.truncated
        assert output.exit_status.exit_code == 0
        running = await self.connection.create_terminal(session_id=session_id, command=sys.executable,
            args=['-c', 'import time; time.sleep(60)'], cwd=str(self.project), output_byte_limit=1024)
        await self.connection.kill_terminal(session_id=session_id, terminal_id=running.terminal_id)
        killed = await self.connection.wait_for_terminal_exit(session_id=session_id, terminal_id=running.terminal_id)
        assert killed.exit_code is None and killed.signal == 'SIGKILL'
        killed_output = await self.connection.terminal_output(session_id=session_id, terminal_id=running.terminal_id)
        assert killed_output.exit_status.signal == 'SIGKILL'
        await self.connection.release_terminal(session_id=session_id, terminal_id=running.terminal_id)
        await self.connection.session_update(session_id=session_id, update=ToolCallProgress(
            sessionUpdate='tool_call_update', tool_call_id='sdk-edit', status='completed'))
        await self.connection.session_update(session_id=session_id, update=AgentMessageChunk(
            sessionUpdate='agent_message_chunk', content=TextContentBlock(type='text', text='SDK_RPC_JOURNEY_COMPLETE')))
        (self.project / 'rpc-receipt.json').write_text(json.dumps({
            'permission': permission.model_dump(mode='json', by_alias=True),
            'output': output.model_dump(mode='json', by_alias=True),
            'killed': killed_output.model_dump(mode='json', by_alias=True)}))
        async with asyncio.timeout(20):
            while not (self.project / 'rpc-painted').exists():
                await asyncio.sleep(.02)
        await self.connection.release_terminal(session_id=session_id, terminal_id=created.terminal_id)
        return PromptResponse(stopReason='end_turn')


if __name__ == '__main__':
    asyncio.run(run_agent(SpecificationPeer()))
