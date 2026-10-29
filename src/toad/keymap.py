"""Stored overrides and views of the keyboard declarations."""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Mapping
from functools import cache
from importlib import import_module
from pkgutil import walk_packages
import re
from types import MappingProxyType
from typing import Annotated, TYPE_CHECKING

import toad
from objectstate import mark_ui_hidden_config

from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import NominalSpelling, NominalText
from textual.binding import Binding, BindingsMap
from textual.dom import DOMNode
from textual.keys import KeyInvocation
from textual.screen import ModalScreen

from toad.key_modes import KeyMode
from toad.setting_declarations import Effect, FamilyChoices
from toad.widget_actions import ApplicationAction


if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.forms.declared_views import DeclaredField


@cache
def discover() -> None:
    """Acquire producer modules once; their own family registries retain membership."""
    DeclaredFamily.discover_package(toad)
    for module in walk_packages(toad.__path__, toad.__name__ + "."):
        if module.ispkg:
            DeclaredFamily.discover_package(import_module(module.name))


class KeymapRefused(ValueError):
    """An invalid keyboard preference the editor may report to its user."""


class KeyInvocationId(NominalText):
    """A saved reference to one concrete command, including its parameters."""


class KeyInvocationSpelling(NominalSpelling[KeyInvocationId]):
    spelling = re.compile(r".+")

    @classmethod
    def from_text(cls, value: str) -> KeyInvocationId:
        reference = KeyInvocationId(value)
        KeymapCatalog.capture(tuple(KeyMode.members_with(KeyMode))).require(reference)
        return reference

    @classmethod
    def encode(cls, value: object) -> str:
        return str(value)


@dataclass(frozen=True)
class KeymapRow:
    declaration: KeyInvocationId
    mode: type[KeyMode]

    @classmethod
    def of(cls, invocation: KeyInvocation, mode: type[KeyMode]) -> KeymapRow:
        return cls(KeyInvocationId(invocation.key_identity()), mode)

    @property
    def binding_id(self) -> str:
        return KeyInvocation.in_mode(self.declaration, self.mode().binding_mode)


@dataclass(frozen=True)
class KeyRemap(KeymapRow):
    keys: tuple[str, ...]


@dataclass(frozen=True)
class KeyConflict:
    first: KeymapRow
    second: KeymapRow
    key: str

    def __str__(self) -> str:
        catalog = KeymapCatalog.capture((self.first.mode,))
        return (f"{self.key}: {catalog.require(self.first.declaration).key_title()} and "
                f"{catalog.require(self.second.declaration).key_title()} "
                f"({FamilyChoices(KeyMode).label(self.first.mode)})")


@dataclass(frozen=True)
class KeymapCatalog:
    """A detached view of the same concrete bindings the native scopes dispatch."""

    invocations: Mapping[KeyInvocationId, KeyInvocation]
    scopes: Mapping[type[KeyMode], tuple[tuple[Binding, ...], ...]]
    default_keys: Mapping[tuple[KeyInvocationId, type[KeyMode]], tuple[str, ...]]

    @classmethod
    def capture(cls, modes: tuple[type[KeyMode], ...]) -> KeymapCatalog:
        discover()
        invocations: dict[KeyInvocationId, KeyInvocation] = {}
        scopes: dict[type[KeyMode], tuple[tuple[Binding, ...], ...]] = {}
        keys: dict[tuple[KeyInvocationId, type[KeyMode]], dict[str, None]] = {}
        for mode in modes:
            native_mode = mode().binding_mode
            application = tuple(binding for declaration in ApplicationAction.declarations()
                                for binding in declaration.exclusive_bindings(native_mode))
            owned = [application]
            for owner in DOMNode.contexts():
                defaults = owner.declared_bindings(native_mode)
                if not issubclass(owner, ModalScreen):
                    defaults = (*defaults, *application)
                owned.append(defaults)
            scopes[mode] = tuple(owned)
            for defaults in owned:
                for key, binding in BindingsMap(defaults):
                    for invocation in binding.invocations():
                        reference = KeyInvocationId(invocation.key_identity())
                        invocations.setdefault(reference, invocation)
                        keys.setdefault((reference, mode), {})[key] = None
        return cls(MappingProxyType(invocations), MappingProxyType(scopes), MappingProxyType({
            (reference, mode): tuple(keys.get((reference, mode), ()))
            for reference in invocations for mode in modes
        }))

    def require(self, reference: KeyInvocationId) -> KeyInvocation:
        try:
            return self.invocations[reference]
        except KeyError:
            raise KeymapRefused(f"Unknown keyboard invocation {reference!r}") from None

    def defaults(self, row: KeymapRow) -> tuple[str, ...]:
        return self.default_keys[row.declaration, row.mode]

    def effective(self, row: KeymapRow, keymap: Keymap) -> tuple[str, ...]:
        return keymap.keys_for(row, self.defaults(row))


@Effect
def apply_keymap(app: ToadApp, field: DeclaredField) -> None:
    app.set_keymap(app.settings.ui.keymap.native())


@mark_ui_hidden_config
@dataclass(frozen=True)
class Keymap:
    bindings: Annotated[tuple[KeyRemap, ...], apply_keymap] = ()

    def __post_init__(self) -> None:
        identities = tuple(remap.binding_id for remap in self.bindings)
        if len(set(identities)) != len(identities):
            raise KeymapRefused("A keyboard declaration may have only one override per mode.")

    def native(self) -> dict[str, str]:
        return {remap.binding_id: ",".join(remap.keys) for remap in self.bindings}

    def keys_for(self, row: KeymapRow, defaults: tuple[str, ...]) -> tuple[str, ...]:
        """The preference alone selects an override; its caller owns the default scope."""
        return next((remap.keys for remap in self.bindings if remap.binding_id == row.binding_id), defaults)

    def changed(self, row: KeymapRow, keys: tuple[str, ...]) -> Keymap:
        """No keys is an explicit unbinding, kept as its own override; Reset restores the defaults."""
        bindings = tuple(remap for remap in self.bindings if remap.binding_id != row.binding_id)
        candidate = replace(self, bindings=(*bindings, KeyRemap(row.declaration, row.mode, keys)))
        return self.checked(candidate, row.mode)

    def checked(self, candidate: Keymap, mode: type[KeyMode]) -> Keymap:
        existing = frozenset(self.conflicts(mode))
        introduced = tuple(conflict for conflict in candidate.conflicts(mode)
                           if conflict not in existing)
        if introduced:
            raise KeymapRefused("Key conflict: " + "; ".join(map(str, introduced)))
        return candidate

    def reset(self, row: KeymapRow) -> Keymap:
        return self.checked(replace(self, bindings=tuple(remap for remap in self.bindings
                                                        if remap.binding_id != row.binding_id)), row.mode)

    def conflicts(self, mode: type[KeyMode]) -> tuple[KeyConflict, ...]:
        """Collisions derive from concrete invocations in the native dispatch scopes."""
        catalog = KeymapCatalog.capture((mode,))
        rows = {row.binding_id: row for invocation in catalog.invocations.values()
                for row in (KeymapRow.of(invocation, mode),)}
        conflicts: set[KeyConflict] = set()
        for defaults in catalog.scopes[mode]:
            # Inspect before Textual resolves clashes by replacing a conflicting binding.
            claims: dict[str, set[str]] = {}
            for default_key, binding in BindingsMap(defaults):
                if binding.id in rows:
                    keys = self.keys_for(rows[binding.id], (default_key,))
                    for key in keys:
                        claims.setdefault(key, set()).add(binding.id)
            for key, identities in claims.items():
                claimed = tuple(sorted(identities))
                for index, first in enumerate(claimed):
                    for second in claimed[index + 1:]:
                        pair = sorted((rows[first], rows[second]), key=lambda row: row.binding_id)
                        first_invocation = catalog.require(pair[0].declaration)
                        second_invocation = catalog.require(pair[1].declaration)
                        if (first_invocation.permits_invocation_overlap(second_invocation)
                                or second_invocation.permits_invocation_overlap(first_invocation)):
                            continue
                        conflicts.add(KeyConflict(pair[0], pair[1], key))
        return tuple(sorted(conflicts, key=str))
