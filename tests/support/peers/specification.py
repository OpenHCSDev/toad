"""Exercises the client side of ACP on the prompt ``SDK_SPECIFICATION_JOURNEY``: session modes,
file write and read, a permission request with a diff, tool call progress, terminals (run, kill, release).

It writes ``rpc-results.json`` in the project when its requests are done, then waits for the test to
release ``painted`` (``Workspace.release``) before it lets go of the terminal and ends the turn.
"""

import asyncio
import json
import sys

from acp.schema import (
    EnvVariable, FileEditToolCallContent, NewSessionResponse, PermissionOption,
    SessionConfigOptionSelect, SessionConfigSelectOption, SetSessionConfigOptionResponse,
    ToolCallProgress, ToolCallStart, ToolCallUpdate,
)

from base import Peer


class SpecificationPeer(Peer):
    def mode(self, current):
        return SessionConfigOptionSelect(id="sdk-mode", name="Mode", category="mode", type="select",
            current_value=current, options=[SessionConfigSelectOption(value="read", name="SDK Read"),
                                            SessionConfigSelectOption(value="write", name="SDK Write")])

    async def new_session(self, cwd, **kwargs):
        response = await super().new_session(cwd, **kwargs)
        return NewSessionResponse(session_id=response.session_id, config_options=[self.mode("read")])

    async def set_config_option(self, config_id, session_id, value, **kwargs):
        assert config_id == "sdk-mode" and value == "write"
        return SetSessionConfigOptionResponse(config_options=[self.mode(value)])

    async def answer(self, session_id: str, text: str) -> None:
        assert text == "SDK_SPECIFICATION_JOURNEY"
        client = self.connection
        path = str(self.project / "sdk-file.txt")
        await client.write_text_file(session_id=session_id, path=path, content="old SDK content")
        read = await client.read_text_file(session_id=session_id, path=path)
        assert read.content == "old SDK content"
        await client.session_update(session_id=session_id, update=ToolCallStart(
            sessionUpdate="tool_call", tool_call_id="sdk-edit", title="SDK edit review",
            kind="edit", status="pending"))
        permission = await client.request_permission(
            session_id=session_id,
            tool_call=ToolCallUpdate(tool_call_id="sdk-edit", title="SDK edit review", kind="edit", content=[
                FileEditToolCallContent(type="diff", path=path, old_text=read.content, new_text="new SDK content")]),
            options=[PermissionOption(option_id="allow", name="Allow SDK edit", kind="allow_once")])
        assert permission.outcome.option_id == "allow"
        await client.write_text_file(session_id=session_id, path=path, content="new SDK content")
        await client.session_update(session_id=session_id, update=ToolCallProgress(
            sessionUpdate="tool_call_update", tool_call_id="sdk-edit", status="in_progress"))
        created = await client.create_terminal(
            session_id=session_id, command=sys.executable,
            args=["-c", 'import os; print(os.environ["SDK_VARIABLE"])'], cwd=str(self.project),
            env=[EnvVariable(name="SDK_VARIABLE", value="SDK_TERMINAL_PAINT")], output_byte_limit=1024)
        exited = await client.wait_for_terminal_exit(session_id=session_id, terminal_id=created.terminal_id)
        assert exited.exit_code == 0 and exited.signal is None
        output = await client.terminal_output(session_id=session_id, terminal_id=created.terminal_id)
        assert "SDK_TERMINAL_PAINT" in output.output and not output.truncated
        assert output.exit_status.exit_code == 0
        running = await client.create_terminal(
            session_id=session_id, command=sys.executable, args=["-c", "import time; time.sleep(60)"],
            cwd=str(self.project), output_byte_limit=1024)
        await client.kill_terminal(session_id=session_id, terminal_id=running.terminal_id)
        killed = await client.wait_for_terminal_exit(session_id=session_id, terminal_id=running.terminal_id)
        assert killed.exit_code is None and killed.signal == "SIGKILL"
        killed_output = await client.terminal_output(session_id=session_id, terminal_id=running.terminal_id)
        assert killed_output.exit_status.signal == "SIGKILL"
        await client.release_terminal(session_id=session_id, terminal_id=running.terminal_id)
        await client.session_update(session_id=session_id, update=ToolCallProgress(
            sessionUpdate="tool_call_update", tool_call_id="sdk-edit", status="completed"))
        await self.say(session_id, "SDK_RPC_JOURNEY_COMPLETE")
        (self.project / "rpc-results.json").write_text(json.dumps({
            "permission": permission.model_dump(mode="json", by_alias=True),
            "output": output.model_dump(mode="json", by_alias=True),
            "killed": killed_output.model_dump(mode="json", by_alias=True)}))
        async with asyncio.timeout(20):
            while not (self.project / "released-painted").exists():
                await asyncio.sleep(.02)
        await client.release_terminal(session_id=session_id, terminal_id=created.terminal_id)


if __name__ == "__main__":
    SpecificationPeer.main()
