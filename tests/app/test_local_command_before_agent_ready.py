"""A declared local command shows its hint and runs while the agent is still starting."""
from toad.session_scope import AgentAttached

from support.agents import peer
from toad.slash_command import NoArgumentsCommand


class CursorProofCommand(NoArgumentsCommand):
    help = "Declaration-only cursor acceptance"
    hint = "DECLARED_CURSOR_HINT"

    async def apply(self, conversation):
        (conversation.project_path / "cursor-command.txt").write_text("Applied actual local declaration")
        return True


async def test_declared_local_command_runs_before_the_agent_is_ready(workspace):
    hold = workspace.project / "hold-acp-startup"
    hold.touch()
    async with workspace.app(size=(130, 44), binding=AgentAttached(peer("completion", name="Physical completion peer",
                                                         identity="completion-acceptance"))) as ui:
        try:
            assert not ui.agent_ready()
            await ui.write_draft(CursorProofCommand().command + " ")
            await ui.until_shows("DECLARED_CURSOR_HINT")
            await ui.press("enter")
            await ui.until((workspace.project / "cursor-command.txt").exists, why="the local command to run")
            assert (workspace.project / "cursor-command.txt").read_text() == "Applied actual local declaration"
        finally:
            hold.unlink()
