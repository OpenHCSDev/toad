"""Native catalog operations derive behavior from the original command owner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from toad.widget_actions import Action
from toad.agent_schema import Command

if TYPE_CHECKING:
    from toad.screens.action_modal import ActionModal


@dataclass(frozen=True)
class CatalogCommandAction(Action, affix="Action"):
    """A bounded selector binding references the original configured record."""

    name: str
    command: Command

    @classmethod
    def bind(cls, name: str, command: Command) -> CatalogCommandAction:
        """Select native completion behavior for the original catalog command."""
        try:
            # External IDs allow hyphens; retain the original ID on the action.
            operation = cls.member_named(name.replace("-", "_"))
        except ValueError:
            # An arbitrary configured script uses explicit result dismissal.
            operation = RunAction
        return operation(name, command)

    @property
    def description(self) -> str:
        return self.command.description

    def command_complete(self, modal: ActionModal, return_code: int) -> None:
        modal.enable_button()


class RunAction(CatalogCommandAction):
    """A configured script requires explicit result dismissal."""


class LoginAction(CatalogCommandAction):
    def command_complete(self, modal: ActionModal, return_code: int) -> None:
        if return_code == 0:
            modal.dismiss(0)
        else:
            modal.enable_button()
