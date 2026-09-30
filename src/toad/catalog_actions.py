"""Native catalog operations derive behavior from the original command owner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from toad.application_actions import NativeAction
from toad.agent_schema import AgentDefinition, Command

if TYPE_CHECKING:
    from toad.screens.agent_modal import AgentModal
    from toad.screens.action_modal import ActionModal


@dataclass(frozen=True)
class CatalogCommandAction(NativeAction, DeclaredFamily, affix="Action"):
    """A bounded selector binding references the original configured record."""

    name: str
    command: Command

    @property
    def description(self) -> str:
        return self.command.description

    def warning(self, agent_name: str) -> str | None:
        return None

    async def apply(self, modal: AgentModal) -> None:
        from toad.screens.action_modal import ActionModal
        from toad.screens.command_edit_modal import CommandEditModal

        modal.action_select.focus()
        edited_command = await modal.app.push_screen_wait(
            CommandEditModal(self.command.command)
        )
        if edited_command is None:
            return
        return_code = await modal.app.push_screen_wait(
            ActionModal(self, modal.agent, edited_command)
        )
        self.finished(modal, return_code)

    def command_complete(self, modal: ActionModal, return_code: int) -> None:
        modal.enable_button()

    def finished(self, modal: AgentModal, return_code: int | None) -> None:
        pass


class RunAction(CatalogCommandAction):
    """A configured script requires explicit result dismissal."""


class InstallAction(CatalogCommandAction):
    def finished(self, modal: AgentModal, return_code: int | None) -> None:
        if return_code == 0:
            modal.add_to_launcher()


class AdapterSetup:
    def warning(self, agent_name: str) -> str:
        return f"{agent_name} requires an ACP adapter to work with Toad. Install from the actions list."


class InstallAcpAction(AdapterSetup, InstallAction):
    """The catalog's original ACP installation ID."""


class InstallAdapterAction(AdapterSetup, InstallAction):
    """The catalog's original adapter installation ID."""


class LoginAction(CatalogCommandAction):
    def command_complete(self, modal: ActionModal, return_code: int) -> None:
        if return_code == 0:
            modal.dismiss(0)
        else:
            modal.enable_button()


@dataclass(frozen=True, eq=False)
class LaunchAction(NativeAction):
    """Native selector resource bound to the original agent definition."""

    agent: AgentDefinition

    @property
    def description(self) -> str:
        return f"Launch {self.agent.name}"

    async def apply(self, modal: AgentModal) -> None:
        from toad.messages import LaunchAgent
        modal.dismiss(LaunchAgent(self.agent.identity))
