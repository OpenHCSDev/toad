"""A viewed object's overrides, with ObjectState owning inheritance and its source."""
import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from agent_comms.nominal.field_codec import FieldCodec
from formbridge.forms.declared_fields import DeclaredField
from objectstate import ObjectState, ObjectStateRegistry, ScopeKey
from objectstate.lazy_factory import LazyDataclassFactory
from pydantic import JsonValue

from toad import atomic
from toad.preferences import SavedSettings
from toad.setting_declarations import Effect, SettingsDeclaration
from toad.settings_scope import SettingsScope
from toad.tab_identity import TabIdentity


@dataclass(frozen=True)
class ObjectSettingsDocument:
    identity: TabIdentity
    values: dict[str, JsonValue]


class ObjectSettingField(DeclaredField):
    """The original concrete declaration, over a lazy field's actual state."""

    @property
    def declaration(self):
        return self.state.defaults.parameter_structure.declarations[self.path.value]

    @property
    def owner_type(self):
        return DeclaredField(self.state.defaults, self.path).owner_type

    @property
    def allows_override(self) -> bool:
        return self.state.admits(self.path.value)

    def reset(self) -> None:
        """The writer resets its actual parameter to that parameter's signature default."""
        state = self.state if self.allows_override else self.state.defaults
        state.reset_parameter(self.path.value)
        if state is self.state.defaults:
            self.state.global_settings.save_sync()

    def edit(self, value):
        if self.allows_override:
            return super().edit(value)
        result = DeclaredField(self.state.defaults, self.path).edit(value)
        self.state.global_settings.save_sync()
        return result


class ObjectConfiguration(ObjectState):
    """One view's explicit values; unassigned fields follow its live defaults."""

    def __init__(self, identity: TabIdentity, global_settings: SavedSettings,
                 directory: Path, owner: SettingsScope) -> None:
        self.global_settings = global_settings
        defaults = global_settings.state
        self.identity, self.defaults, self.owner = identity, defaults, owner
        self.path = directory / "objects" / f"{identity.mode_name}.json"
        scope = str(ScopeKey.of("view", identity.mode_name))
        if ObjectStateRegistry.get_by_scope(scope) is not None:
            raise ValueError(f"Settings already open for {identity}")
        lazy_type = LazyDataclassFactory.make_lazy_simple(type(defaults.object_instance))
        super().__init__(lazy_type(), scope_id=scope, parent_state=defaults)
        if self.path.exists():
            document = FieldCodec.decode(ObjectSettingsDocument, FieldCodec.parse(self.path.read_text("utf-8")))
            if document.identity != identity:
                raise ValueError(f"Settings identity does not match {self.path}")
            for path, encoded in document.values.items():
                if path not in self.editable_paths:
                    raise ValueError(f"{path} cannot be overridden for {identity}")
                field = self.field(path)
                field.edit(FieldCodec.decode(field.annotation, encoded))
        self.mark_saved()
        ObjectStateRegistry.register(self)
        self.on_resolved_changed(self.apply_changes)
        self.on_state_changed(self.save_changes)

    def field(self, path: str) -> ObjectSettingField:
        return ObjectSettingField(self, self.parameter_structure.path(path))

    @cached_property
    def editable_paths(self) -> frozenset[str]:
        return frozenset(path.value for path in self.parameter_structure.leaf_paths()
                         if self.admits(path.value))

    def admits(self, path: str) -> bool:
        field = self.field(path)
        owner = field.owner_type
        return (issubclass(owner, SettingsDeclaration)
                and owner.admits_field(field.path.field_name, self.owner))

    def update_parameter(self, param_name: str, value: object) -> set[str]:
        if param_name not in self.editable_paths:
            raise ValueError(f"{param_name} cannot be overridden for {self.identity}")
        return super().update_parameter(param_name, value)

    def apply_changes(self, paths: set[str]) -> None:
        for path in paths & self.editable_paths:
            field = self.field(path)
            if (effect := field.metadata(Effect)) is not None:
                effect.apply(self.owner, field)

    def save_changes(self, paths: set[str]) -> None:
        if not paths:
            return
        values = {path: FieldCodec.encode(value, self.field(path).annotation)
                  for path, value in self.get_current_values().items()
                  if path in self.editable_paths and value is not None}
        text = json.dumps(FieldCodec.encode(ObjectSettingsDocument(self.identity, values)), indent=2, allow_nan=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write(str(self.path), text)
        self.mark_saved()

    def close(self) -> None:
        self.off_resolved_changed(self.apply_changes)
        self.off_state_changed(self.save_changes)
        ObjectStateRegistry.unregister(self)
