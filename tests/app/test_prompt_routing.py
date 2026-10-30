"""Typed text goes to the agent as written; only shell mode runs a command."""
from toad.session_scope import AgentAttached

from support.agents import peer


async def test_command_looking_text_is_sent_to_the_agent_not_the_shell(workspace):
    async with workspace.app(binding=AgentAttached(peer("echo"))) as ui:
        await ui.until_agent_ready()
        # "!" on an empty prompt enters shell mode (cfe1bb492); that is tests/textual/test_prompt_shell_mode.py's.
        sent = ["openhcs", "open the project", "git status", "python", "$100 budget", "@peer"]
        for text in sent:
            await ui.type(text)
            assert ui.draft() == text
            await ui.press("enter")
            await ui.until(lambda: workspace.prompts_received()[-1:] == [text], why=f"{text!r} at the agent")
            assert ui.draft() == ""
        assert workspace.prompts_received() == sent


async def test_enter_sends_the_whole_multiline_draft_and_ctrl_j_adds_a_line(workspace):
    async with workspace.app(binding=AgentAttached(peer("echo"))) as ui:
        await ui.until_agent_ready()
        for text in ("first line\nsecond line", "```python\nprint('hello')\n```"):
            await ui.write_draft(text)
            await ui.press("enter")
            await ui.until(lambda: workspace.prompts_received()[-1:] == [text], why="the multiline draft at the agent")
            assert ui.draft() == ""
        sent = len(workspace.prompts_received())
        await ui.write_draft("line one")
        await ui.press("ctrl+j", *"line", "space", *"two", "ctrl+j", *"line", "space", *"three")
        assert ui.draft() == "line one\nline two\nline three"
        assert len(workspace.prompts_received()) == sent
        await ui.press("enter")
        await ui.until(lambda: workspace.prompts_received()[-1:] == ["line one\nline two\nline three"])
