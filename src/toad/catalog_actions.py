"""Native catalog operations derive behavior from the original command owner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.nominal.declared_family import DeclaredFamily
from toad.agent_schema import Command

if TYPE_CHECKING:
    from toad.screens.action_modal import ActionModal


@dataclass(frozen=True)
class CatalogCommandAction(DeclaredFamily, affix="Action"):
    """A bounded selector binding references the original configured record.

    Its whole interface is the one `ActionModal` reads: `command_complete` and `description`.
    It is not a key-binding `Action`, which declares `apply(context)` abstract for members a
    widget applies to a context; inheriting that made every member uninstantiable, and login
    died with "Can't instantiate abstract class RunAction without an implementation for
    abstract method 'apply'" (Toad log WorkerFailed_2026-11-07T14_00_38, at `provider_login`).
    """

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
