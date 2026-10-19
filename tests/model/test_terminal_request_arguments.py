"""A terminal the agent asks for runs the exact executable and arguments it named, spaces and quotes included."""



async def test_executable_and_arguments_reach_the_process_unchanged(app_agents, tmp_path):
    executable = tmp_path / "argv with spaces # %.sh"
    executable.write_text("#!/bin/sh\nprintf '%s|%s' \"$1\" \"$2\"\n")
    executable.chmod(0o700)
    argument = "literal # % ' \" spaces"
    agent = app_agents.detached_agent("argv-session")
    calls = iter(range(1, 100))

    async def request(method, **params):
        response = await agent.server.call({"jsonrpc": "2.0", "id": next(calls), "method": method,
                                            "params": {"sessionId": agent.session_id, **params}})
        assert "error" not in response, response
        return response["result"]

    try:
        terminal_id = (await request("terminal/create", command=str(executable), args=[argument, ""],
                                     cwd=str(tmp_path)))["terminalId"]
        execution = agent.controller.terminals.require(terminal_id)
        process = await execution.operation.process()
        assert (await request("terminal/wait_for_exit", terminalId=terminal_id))["exitCode"] == 0
        assert (await request("terminal/output", terminalId=terminal_id))["output"] == argument + "|"
        await request("terminal/release", terminalId=terminal_id)
        assert execution.operation.outcome().finished and process.master.closed and process.child.retired
        assert not agent.controller.terminals.executions
    finally:
        await agent.stop()
