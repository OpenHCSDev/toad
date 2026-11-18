"""Stored overrides and views of the keyboard declarations."""
from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import cache, cached_property
from importlib import import_module
from pkgutil import walk_packages
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import NominalSpelling, NominalText
from objectstate import mark_ui_hidden_config
from textual.binding import BindingsMap
from textual.dom import DOMNode
from formbridge.key_declarations import KeyInvocation
from textual.screen import ModalScreen

import toad
from toad.key_modes import KeyMode
from toad.menus import MenuCommand
from toad.setting_declarations import Effect, FamilyChoices
from toad.client.application_actions import ApplicationAction
from toad.widget_actions import DeclaredWidgetActions

if TYPE_CHECKING:
    from formbridge.forms.declared_fields import DeclaredField

    from toad.app import ToadApp


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
    """One concrete command, including its parameters, as its declaration names it now:
    `module.qualname`, with `:`-joined qualified parts for parameterised bindings."""


class KeyInvocationSpelling(NominalSpelling[KeyInvocationId]):
    """A saved keymap names a command by its declaration, not by the module it lives in:
    moving a class between modules must not unbind a user's keys. The catalog owns both
    directions (`KeymapCatalog.resolve` / `KeymapCatalog.spelling`)."""

    spelling = re.compile(r".+")

    @classmethod
    def from_text(cls, value: str) -> KeyInvocationId:
        return KeymapCatalog.capture(tuple(KeyMode.members_with(KeyMode))).resolve(value)

    @classmethod
    def encode(cls, value: object) -> str:
        return KeymapCatalog.capture(tuple(KeyMode.members_with(KeyMode))).spelling(
            KeyInvocationId(str(value)))


@dataclass(frozen=True)
class SpelledIdentity:
    """A command identity read as its `:`-joined dotted parts, each split at the dots. The
    part after a part's module is its qualname; comparing tails of parts is how a saved
    spelling finds its declaration wherever that declaration's module now is."""

    parts: tuple[tuple[str, ...], ...]

    @classmethod
    def of(cls, text: str) -> SpelledIdentity:
        return cls(tuple(tuple(part.split(".")) for part in text.split(":")))

    def qualname_lengths(self) -> tuple[int, ...]:
        """How many trailing names of each part are its qualname: everything after the longest
        prefix that is an imported module (a catalog identity's declarations are imported)."""
        return tuple(next((len(part) - cut for cut in range(len(part) - 1, 0, -1)
                           if ".".join(part[:cut]) in sys.modules), len(part))
                     for part in self.parts)

    def shared_tail(self, other: SpelledIdentity, minimum: tuple[int, ...]) -> int | None:
        """Total trailing names this spelling shares with `other`, part by part; None unless
        every part shares at least its `minimum` (the other's qualname)."""
        if len(self.parts) != len(other.parts):
            return None
        total = 0
        for mine, theirs, least in zip(self.parts, other.parts, minimum):
            shared = 0
            while shared < min(len(mine), len(theirs)) and mine[-1 - shared] == theirs[-1 - shared]:
                shared += 1
            if shared < least:
                return None
            total += shared
        return total

    def tail(self, lengths: tuple[int, ...]) -> str:
        return ":".join(".".join(part[-length:]) for part, length in zip(self.parts, lengths))


@dataclass(frozen=True)
class KeymapRow:
    declaration: KeyInvocationId
    mode: type[KeyMode]

    @classmethod
    def of(cls, invocation: KeyInvocation, mode: type[KeyMode]) -> KeymapRow:
        return cls(KeyInvocationId(invocation.key_identity()), mode)

    @cached_property
    def binding_id(self) -> str:
        return KeyInvocation.in_mode(self.declaration, self.mode.binding_mode())


@dataclass(frozen=True)
class ScopedClaim:
    """One default claim in a dispatch scope: the row the keymap edits and its declared keys."""

    row: KeymapRow
    keys: tuple[str, ...]


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
    scopes: Mapping[type[KeyMode], tuple[tuple[ScopedClaim, ...], ...]]
    default_keys: Mapping[tuple[KeyInvocationId, type[KeyMode]], tuple[str, ...]]
    rows: Mapping[type[KeyMode], Mapping[str, KeymapRow]]

    @classmethod
    def capture(cls, modes: tuple[type[KeyMode], ...]) -> KeymapCatalog:
        """The catalog of the classes declared now. Reading those declarations is a class walk;
        building their bindings is not, so it runs once per distinct set of declarations."""
        discover()
        return cls.of(tuple(modes), DOMNode.descendants(), tuple(ApplicationAction.declarations()))

    @classmethod
    @cache
    def of(
        cls,
        modes: tuple[type[KeyMode], ...],
        contexts: tuple[type[DOMNode], ...],
        actions: tuple[type[ApplicationAction], ...],
    ) -> KeymapCatalog:
        """The modes' catalogs together: each mode is built once, whichever set asks for it (the
        editor shows every mode; a conflict check or its message reads one)."""
        catalogs = tuple(cls.declared(mode, contexts, actions) for mode in modes)
        invocations: dict[KeyInvocationId, KeyInvocation] = {}
        for catalog in catalogs:
            for reference, invocation in catalog.invocations.items():
                invocations.setdefault(reference, invocation)
        return cls(MappingProxyType(invocations), MappingProxyType({
            mode: scopes for catalog in catalogs for mode, scopes in catalog.scopes.items()
        }), MappingProxyType({
            (reference, mode): catalog.default_keys.get((reference, mode), ())
            for reference in invocations for catalog in catalogs for mode in catalog.scopes
        }), MappingProxyType({mode: cls.mode_rows(mode, invocations) for mode in modes}))

    @staticmethod
    def mode_rows(mode: type[KeyMode], invocations: Mapping[KeyInvocationId, KeyInvocation],
                  ) -> Mapping[str, KeymapRow]:
        return MappingProxyType({row.binding_id: row for reference in invocations
                                 for row in (KeymapRow(reference, mode),)})

    @classmethod
    @cache
    def declared(
        cls,
        mode: type[KeyMode],
        contexts: tuple[type[DOMNode], ...],
        actions: tuple[type[ApplicationAction], ...],
    ) -> KeymapCatalog:
        """One mode's catalog, a function of the declarations it is given, so a context or action
        declared later is a different argument and never a stale answer. Families a context's
        keymap_claims reads for itself (Menu reads MenuCommand's members) are settled by
        discover(), which capture runs first and which imports every toad module."""
        native_mode = mode.binding_mode()
        application = tuple(BindingsMap(
            binding for declaration in actions
            for binding in DeclaredWidgetActions.exclusive_bindings(declaration, native_mode)
        ).keymap_claims())
        owned = [application]
        for owner in contexts:
            defaults = owner.keymap_claims(native_mode)
            if not issubclass(owner, ModalScreen):
                defaults = (*defaults, *application)
            owned.append(defaults)
        invocations: dict[KeyInvocationId, KeyInvocation] = {}
        keys: dict[KeyInvocationId, dict[str, None]] = {}
        scoped: list[tuple[ScopedClaim, ...]] = []
        for defaults in owned:
            claims: list[ScopedClaim] = []
            for claim in defaults:
                reference = KeyInvocationId(claim.invocation.key_identity())
                invocations.setdefault(reference, claim.invocation)
                claims.append(ScopedClaim(KeymapRow(reference, mode), claim.keys))
                for key in claim.keys:
                    keys.setdefault(reference, {})[key] = None
            scoped.append(tuple(claims))
        return cls(MappingProxyType(invocations), MappingProxyType({mode: tuple(scoped)}),
                   MappingProxyType({(reference, mode): tuple(keys.get(reference, ()))
                                     for reference in invocations}),
                   MappingProxyType({mode: cls.mode_rows(mode, invocations)}))

    @staticmethod
    def menu_keys(command: MenuCommand, mode: type[KeyMode], keymap: Keymap) -> tuple[str, ...]:
        declaration = type(command)
        return keymap.keys_for(KeymapRow.of(declaration, mode), declaration.default_keys())

    def require(self, reference: KeyInvocationId) -> KeyInvocation:
        try:
            return self.invocations[reference]
        except KeyError:
            raise KeymapRefused(f"Unknown keyboard invocation {reference!r}") from None

    @cached_property
    def spelled(self) -> Mapping[KeyInvocationId, tuple[SpelledIdentity, tuple[int, ...]]]:
        """Each declared identity split into names, with each part's qualname length."""
        return MappingProxyType({reference: (identity, identity.qualname_lengths())
                                 for reference in self.invocations
                                 for identity in (SpelledIdentity.of(reference),)})

    def resolve(self, saved: str) -> KeyInvocationId:
        """The declared command a saved spelling names: the one sharing the longest tail with
        it, covering at least its whole qualname. A module path that moved, or the short
        spelling `spelling` writes, still finds its command; a tie or no match refuses."""
        wanted = SpelledIdentity.of(saved)
        scored = [(shared, reference) for reference, (identity, least) in self.spelled.items()
                  for shared in (wanted.shared_tail(identity, least),) if shared is not None]
        if not scored:
            raise KeymapRefused(f"Unknown keyboard invocation {saved!r}")
        best = max(shared for shared, _ in scored)
        chosen = [reference for shared, reference in scored if shared == best]
        if len(chosen) > 1:
            raise KeymapRefused(f"Keyboard invocation {saved!r} could name any of "
                                f"{', '.join(sorted(chosen))}; spell its module too")
        return chosen[0]

    def spelling(self, reference: KeyInvocationId) -> str:
        """The shortest tail of the identity that `resolve` maps back to it alone: the bare
        qualname unless another declaration shares it, then with its module's last names."""
        self.require(reference)
        identity, least = self.spelled[reference]
        lengths = least
        while True:
            text = identity.tail(lengths)
            try:
                if self.resolve(text) == reference:
                    return text
            except KeymapRefused:
                pass
            grown = tuple(min(length + 1, len(part)) for length, part in zip(lengths, identity.parts))
            if grown == lengths:
                return str(reference)
            lengths = grown

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
        if len(self.overrides) != len(self.bindings):
            raise KeymapRefused("A keyboard declaration may have only one override per mode.")

    @cached_property
    def overrides(self) -> Mapping[str, tuple[str, ...]]:
        """Each remap's keys by its binding id: every lookup reads this one map."""
        return MappingProxyType({remap.binding_id: remap.keys for remap in self.bindings})

    def native(self) -> dict[str, str]:
        return {binding_id: ",".join(keys) for binding_id, keys in self.overrides.items()}

    def keys_for(self, row: KeymapRow, defaults: tuple[str, ...]) -> tuple[str, ...]:
        """The preference alone selects an override; its caller owns the default scope."""
        return self.overrides.get(row.binding_id, defaults)

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
        rows = catalog.rows[mode]
        conflicts: set[KeyConflict] = set()
        for defaults in catalog.scopes[mode]:
            # A scope is ordered: the declared defaults set precedence, and dispatch runs the
            # first claim on a key and shadows the rest (the prompt's CopyOrClearInputAction over
            # TextArea.action_copy, TextArea's own end over navigation's ScrollEnd). Two declared
            # claims on one key are that precedence, never a collision. A collision is a key a
            # remap moved onto a row that another claim in the scope also holds.
            claims: dict[str, dict[str, bool]] = {}
            for claim in defaults:
                row = claim.row
                for key in self.keys_for(row, claim.keys):
                    held = claims.setdefault(key, {})
                    held[row.binding_id] = held.get(row.binding_id, False) or key not in claim.keys
            for key, held in claims.items():
                claimed = tuple(sorted(held))
                for index, first in enumerate(claimed):
                    for second in claimed[index + 1:]:
                        if not (held[first] or held[second]):
                            continue
                        pair = sorted((rows[first], rows[second]), key=lambda row: row.binding_id)
                        first_invocation = catalog.require(pair[0].declaration)
                        second_invocation = catalog.require(pair[1].declaration)
                        if (first_invocation.permits_invocation_overlap(second_invocation)
                                or second_invocation.permits_invocation_overlap(first_invocation)):
                            continue
                        conflicts.add(KeyConflict(pair[0], pair[1], key))
        return tuple(sorted(conflicts, key=str))
