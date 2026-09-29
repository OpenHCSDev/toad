"""The package inventory's declared fields and decision capabilities."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Literal

from agent_comms.declared_family import DeclaredFamily


class InventoryScope(DeclaredFamily, affix="Scope"):
    @classmethod
    @abstractmethod
    def rows(cls, inventory: Inventory) -> tuple[Declaration, ...]: ...

    @classmethod
    def allows_trust_decision(cls) -> bool:
        return False


class UserScope(InventoryScope):
    @classmethod
    def rows(cls, inventory: Inventory) -> tuple[Declaration, ...]:
        return inventory.declarations.user


class ProjectScope(InventoryScope):
    @classmethod
    def rows(cls, inventory: Inventory) -> tuple[Declaration, ...]:
        return inventory.declarations.project

    @classmethod
    def allows_trust_decision(cls) -> bool:
        return True


class CallPolicy(DeclaredFamily, affix="Policy"):
    @classmethod
    def allows_calls(cls) -> bool:
        return True


class AllowPolicy(CallPolicy):
    pass


class AskPolicy(CallPolicy):
    pass


class UnavailablePolicy(CallPolicy):
    @classmethod
    def allows_calls(cls) -> bool:
        return False


class DeclarationStatus(DeclaredFamily, affix="Status"):
    @classmethod
    def validate(cls, effective: bool, enabled: bool, policy: type[CallPolicy]) -> None:
        if not effective or policy.allows_calls():
            raise ValueError("Inconsistent declaration state")

    @classmethod
    def allows_call_decision(cls) -> bool:
        return False


class ApprovedStatus(DeclarationStatus):
    @classmethod
    def validate(cls, effective: bool, enabled: bool, policy: type[CallPolicy]) -> None:
        if not effective or not enabled:
            raise ValueError("Approved declaration must be enabled and effective")
        if not policy.allows_calls():
            raise ValueError("Approved declaration needs a call policy")

    @classmethod
    def allows_call_decision(cls) -> bool:
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
    @classmethod
    def validate(cls, effective: bool, enabled: bool, policy: type[CallPolicy]) -> None:
        if effective or policy.allows_calls():
            raise ValueError("Shadowed declaration cannot be effective or authorize calls")


@dataclass(frozen=True)
class TransportSummary:
    type: Literal["stdio"]
    argument_count: int = field(metadata={"wire_name": "argumentCount"})
    cwd: Literal["project"]
    env_names: tuple[str, ...] = field(metadata={"wire_name": "envNames"})
    env_from: tuple[tuple[str, str], ...] = field(metadata={"wire_name": "envFrom"})

    def __post_init__(self) -> None:
        if not 0 <= self.argument_count <= 256:
            raise ValueError("Unsupported argument count")
        for names in (self.env_names, tuple(name for name, _ in self.env_from)):
            if len(names) > 128 or len(set(names)) != len(names):
                raise ValueError("Invalid environment names")
        names = (*self.env_names, *(name for pair in self.env_from for name in pair))
        if any(not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name) for name in names):
            raise ValueError("Invalid environment mapping")

    def render(self) -> str:
        names = ', '.join(self.env_names) or '(none)'
        mappings = ', '.join(f'{name}={source}' for name, source in self.env_from) or '(none)'
        return f"    stdio / project cwd · args {self.argument_count} · env names {names} · envFrom {mappings}"


@dataclass(frozen=True)
class Declaration:
    id: str
    scope: type[InventoryScope]
    digest: str
    effective: bool
    enabled: bool
    status: type[DeclarationStatus]
    call_policy: type[CallPolicy] = field(metadata={"wire_name": "callPolicy"})
    transport: TransportSummary

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", self.id):
            raise ValueError("Invalid declaration identifier")
        if not re.fullmatch(r"[a-f0-9]{64}", self.digest):
            raise ValueError("Invalid declaration digest")
        self.status.validate(self.effective, self.enabled, self.call_policy)

    @property
    def option_id(self) -> str:
        return f"{self.scope.declared_name}:{self.id}"

    def render(self) -> tuple[str, ...]:
        disposition = 'effective' if self.effective else 'shadowed'
        return (
            f"  {self.id} · {self.status.declared_name} · calls {self.call_policy.declared_name}"
            f" · {disposition}",
            f"    SHA-256: {self.digest}",
            self.transport.render(),
        )


@dataclass(frozen=True)
class InventoryDeclarations:
    user: tuple[Declaration, ...]
    project: tuple[Declaration, ...]


@dataclass(frozen=True)
class InventoryLive:
    state: Literal["not_running"]


@dataclass(frozen=True)
class Inventory:
    version: Literal[2]
    project_root: str = field(metadata={"wire_name": "projectRoot"})
    project_trusted_saved: bool = field(metadata={"wire_name": "projectTrustedSaved"})
    project_config_skipped: bool = field(metadata={"wire_name": "projectConfigSkipped"})
    lifetime: Literal["active_pi_turn"]
    live: InventoryLive
    declarations: InventoryDeclarations

    def __post_init__(self) -> None:
        for scope in InventoryScope.members_with(InventoryScope):
            rows = scope.rows(self)
            if len(rows) > 256 or len({row.id for row in rows}) != len(rows):
                raise ValueError("Invalid or duplicate declarations")
            if any(row.scope != scope for row in rows):
                raise ValueError("Declaration scope mismatch")
        effective = [row.id for row in self.rows if row.effective]
        if len(set(effective)) != len(effective):
            raise ValueError("Multiple effective declarations")
        if not self.project_trusted_saved:
            if self.declarations.project or any(row.status.allows_call_decision() for row in self.rows):
                raise ValueError("Approval without saved project trust")

    @property
    def root(self) -> Path:
        return Path(self.project_root)

    @property
    def rows(self) -> tuple[Declaration, ...]:
        return tuple(row for scope in InventoryScope.members_with(InventoryScope) for row in scope.rows(self))

    def render(self) -> str:
        lines = [
            "Pi MCP declarations · static package snapshot (not live)",
            f"Saved Pi project trust: {'yes' if self.project_trusted_saved else 'no'}",
            f"Project config skipped before trust: {'yes' if self.project_config_skipped else 'no'}",
            "Runtime: not running in this snapshot; live status is not asserted.",
            "Decisions apply to the next Pi turn. This is not active server state.",
            "Actions launch the installed package CLI in a visible POSIX PTY; it owns",
            "the complete display, exact digest challenge and ledger write. Toad never",
            "auto-answers and cannot undo a decision the package already committed.",
        ]
        for scope in InventoryScope.members_with(InventoryScope):
            rows = scope.rows(self)
            lines.append(f"\n{scope.declared_name.title()} declarations ({len(rows)}):")
            for row in rows:
                lines.extend(row.render())
        return '\n'.join(lines)
