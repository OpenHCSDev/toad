"""Twenty submissions in a row and then typed keys all reach the agent, in order and none lost."""
from toad.session_scope import AgentAttached

from support.agents import peer


async def test_consecutive_submissions_and_keys_typed_after_them_reach_the_agent_in_order(workspace):
    async with workspace.app(binding=AgentAttached(peer("echo"))) as ui:
        await ui.until_agent_ready()
        messages = [f"message {index}" for index in range(20)]
        for index, text in enumerate(messages):
            await ui.write_draft(text)
            await ui.press("enter")
            await ui.until(lambda: len(workspace.prompts_received()) == index + 1, why=f"{text!r} at the agent")
        assert workspace.prompts_received() == messages
        await ui.press("f", "a", "s", "t", "enter")
        await ui.until(lambda: workspace.prompts_received()[-1:] == ["fast"], why="typed keys at the agent")
