"""Nominal interpretation of the current package-owned inventory boundary."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily

if TYPE_CHECKING:
    from toad.mcp_inventory import Declaration, Inventory


class InventoryTerm:
    def __str__(self) -> str:
        return self.declared_name


@dataclass(frozen=True)
class InventoryScope(InventoryTerm, DeclaredFamily, affix="Scope"):
    @abstractmethod
    def rows(self, inventory: Inventory) -> tuple[Declaration, ...]:
        """Select the rows declared in this scope."""

    def allows_trust_decision(self) -> bool:
        return False


class UserScope(InventoryScope):
    def rows(self, inventory: Inventory) -> tuple[Declaration, ...]:
        return inventory.user


class ProjectScope(InventoryScope):
    def rows(self, inventory: Inventory) -> tuple[Declaration, ...]:
        return inventory.project

    def allows_trust_decision(self) -> bool:
        return True


@dataclass(frozen=True)
class DeclarationStatus(InventoryTerm, DeclaredFamily, affix="Status"):
    def validate(self, effective: bool, policy: str) -> None:
        if not effective or policy != "unavailable":
            raise ValueError("Inconsistent declaration state")

    def allows_call_decision(self) -> bool:
        return False


class ApprovedStatus(DeclarationStatus):
    def validate(self, effective: bool, policy: str) -> None:
        if not effective:
            raise ValueError("Approved declaration must be effective")

    def allows_call_decision(self) -> bool:
        return True


class DisabledStatus(DeclarationStatus):
    pass


class DeniedStatus(DeclarationStatus):
    pass


class TrustRequiredStatus(DeclarationStatus):
    pass


class UnsupportedEnvStatus(DeclarationStatus):
    pass


class ShadowedStatus(DeclarationStatus):
    def validate(self, effective: bool, policy: str) -> None:
        if effective or policy != "unavailable":
            raise ValueError("Shadowed declaration cannot be effective or authorize calls")
