"""Textual-facing: the prompt widget's shell mode lasts for one submission.

Shell mode has no key of its own (recalling a shell entry from input history
sets it), so this test sets the widget's flag directly.
"""

from support.agents import peer
from toad.widgets.prompt import Prompt


async def test_shell_mode_runs_one_command_then_returns_to_agent_input(workspace):
    async with workspace.app(agent=peer("echo")) as ui:
        await ui.until_agent_ready()
        app, _pilot = ui.textual
        prompt = app.selected_session.query_one(Prompt)
        prompt.shell_mode = True
        await ui.step()
        assert prompt.shell_mode and ui.draft() == ""
        await ui.type("echo SHELL_RAN")
        await ui.press("enter")
        await ui.until(lambda: not prompt.shell_mode, why="shell mode to end after one command")
        await ui.until_shows("SHELL_RAN")
        await ui.type("open again")
        await ui.press("enter")
        await ui.until(lambda: workspace.prompts_received() == ["open again"], why="the next input at the agent")
