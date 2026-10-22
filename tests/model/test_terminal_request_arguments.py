"""A terminal the agent asks for runs the exact executable and arguments it named, spaces and quotes included."""



async def test_executable_and_arguments_reach_the_process_unchanged(app_agents, tmp_path):
    executable = tmp_path / "argv with spaces # %.sh"
    executable.write_text("#!/bin/sh\nprintf '%s|%s' \"$1\" \"$2\"\n")
    executable.chmod(0o700)
    argument = "literal # % ' \" spaces"
    agent = app_agents.detached_agent("argv-session")
    try:
        terminal_id = (await agent.controller.terminal_create(agent.session_id, str(executable),
                                     None, args=[argument, ""], cwd=str(tmp_path))).terminal_id
        execution = agent.controller.terminals.require(terminal_id)
        process = await execution.operation.process()
        assert (await agent.controller.terminal_wait_for_exit(agent.session_id, terminal_id)).exit_code == 0
        assert (await agent.controller.terminal_output(agent.session_id, terminal_id)).output == argument + "|"
        await agent.controller.terminal_release(agent.session_id, terminal_id)
        assert execution.operation.outcome().finished and process.master.closed and process.child.retired
        assert not agent.controller.terminals.executions
    finally:
        await agent.stop()
