"""Hierarchical agent settings hydrated into real linked ObjectStates.

Core owns ``GlobalAgentSettings`` (``Global -> Project -> [Channel] -> Thread``) and
exposes each scope's authored ancestor layers via ``CommsAgentSettingsTool`` /
``CommsSetAgentSettingsTool``. This module hydrates those ancestor layers into one linked
``ObjectState`` chain registered under an isolated ``ScopeKey`` namespace so both Textual's
``ObjectFormView`` and Qt's ``QtObjectFormView`` render live inheritance, exact provenance
labels, and Reset-to-inherit with zero duplicate form code.
"""

from __future__ import annotations

import itertools
from abc import abstractmethod
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, fields
from functools import cache, singledispatch
from typing import ClassVar

from agent_comms.cli_support.cli_failures import CLI_FAILURES
from agent_comms.nominal.field_codec import FieldCodec, FieldPlan
from agent_comms.registry.agent_settings import GlobalAgentSettings
from agent_comms.registry.agent_settings_wire import (
    AgentOnlySettingsScope,
    AgentSettingsScope,
    ChannelSettingsScope,
    GlobalSettingsScope,
    ProjectSettingsScope,
    ScopedSettingsProjection,
    ThreadSettingsScope,
)
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tools.sidebar import (
    CommsAgentSettingsTool,
    CommsSetAgentSettingsTool,
)
from metaclass_registry import AbstractHooksMeta
from objectstate import LazyDataclassFactory, ObjectState, ObjectStateRegistry, ScopeKey
from pydantic import JsonValue
from python_introspect import ParameterInfo

from toad.client.sidebar_panels import PanelSpec
from toad.object_configuration import ObjectSettingField

_CHAIN_IDS = itertools.count(1)


@singledispatch
def scope_label(scope: AgentSettingsScope) -> str:
    """Plain-English label for one nominal ``AgentSettingsScope`` member."""
    return scope.scope_id or "Global"


@scope_label.register(GlobalSettingsScope)
def _global_scope_label(_scope: GlobalSettingsScope) -> str:
    return "Global"


@scope_label.register(ProjectSettingsScope)
def _project_scope_label(scope: ProjectSettingsScope) -> str:
    return f"Project {scope.project}"


@scope_label.register(ChannelSettingsScope)
def _channel_scope_label(scope: ChannelSettingsScope) -> str:
    return f"Channel {scope.channel}"


@scope_label.register(ThreadSettingsScope)
def _thread_scope_label(scope: ThreadSettingsScope) -> str:
    return f"Thread {scope.thread}"


@scope_label.register(AgentOnlySettingsScope)
def _agent_scope_label(scope: AgentOnlySettingsScope) -> str:
    return f"Agent {scope.thread}"


@dataclass(frozen=True, slots=True)
class AgentGroupSchema:
    """One top-level dataclass group declared on ``GlobalAgentSettings``."""

    name: str
    concrete_type: type
    lazy_type: type
    plans: dict[str, FieldPlan]


@cache
def agent_group_schemas() -> tuple[AgentGroupSchema, ...]:
    defaults = GlobalAgentSettings()
    groups: list[AgentGroupSchema] = []
    for item in fields(GlobalAgentSettings):
        concrete_type = type(getattr(defaults, item.name))
        lazy_type = LazyDataclassFactory.make_lazy_simple(concrete_type)
        plans = {plan.name: plan for plan in FieldCodec.field_plans(concrete_type)}
        groups.append(AgentGroupSchema(item.name, concrete_type, lazy_type, plans))
    return tuple(groups)


@cache
def agent_field_plans() -> dict[str, tuple[AgentGroupSchema, FieldPlan]]:
    return {
        f"{group.name}.{plan.name}": (group, plan)
        for group in agent_group_schemas()
        for plan in group.plans.values()
    }


@cache
def lazy_global_agent_settings_type() -> type:
    agent_group_schemas()
    return LazyDataclassFactory.make_lazy_simple(GlobalAgentSettings)


def _new_lazy_agent_settings() -> object:
    """Fresh lazy ``GlobalAgentSettings`` with every group lazy so every leaf starts ``None``."""
    return lazy_global_agent_settings_type()()


@cache
def _concrete_declarations() -> tuple[dict[str, ParameterInfo], dict[str, type]]:
    """Concrete ``ParameterInfo`` and owning group type per path on ``GlobalAgentSettings``."""
    probe = ObjectState(GlobalAgentSettings(), scope_id="")
    owners: dict[str, type] = {}
    for group in agent_group_schemas():
        owners[group.name] = GlobalAgentSettings
        for field_name in group.plans:
            owners[f"{group.name}.{field_name}"] = group.concrete_type
    return (dict(probe.parameter_structure.declarations), owners)


class AgentSettingField(ObjectSettingField):
    """One ``GlobalAgentSettings`` field on a scoped ``AgentScopeState``."""

    @property
    def declaration(self) -> ParameterInfo:
        declarations, _owners = _concrete_declarations()
        return declarations[self.path.value]

    @property
    def owner_type(self) -> type:
        _declarations, owners = _concrete_declarations()
        return owners[self.path.value]

    @property
    def allows_override(self) -> bool:
        return True

    @property
    def overridden(self) -> bool:
        return self.state.parameters[self.path.value] is not None

    @property
    def source_text(self) -> str:
        if self.overridden:
            return f"Override for {self.state.scope_label}"
        return self.state.inherited_label(self.path.value)

    @property
    def source_detail(self) -> str:
        scope_id, owner = self.state.get_provenance(self.path.value)
        core_scope = self.state.chain.core_scope_for_registry(scope_id)
        return f"{owner.__module__}.{owner.__qualname__} · {core_scope}"

    def validate(self, value: object) -> None:
        """Validate through Core's FieldCodec round-trip plus annotated bounds."""
        _group, plan = agent_field_plans()[self.path.value]
        encoded = FieldCodec.encode(value, plan.annotation)
        FieldCodec.decode(plan.annotation, encoded)
        if not isinstance(value, type):
            super().validate(value)

    def reset(self) -> None:
        self.state.reset_parameter(self.path.value)

    def edit(self, value: object) -> None:
        self.validate(value)
        self.state.update_parameter(self.path.value, value)


class AgentScopeState(ObjectState):
    """One scope layer in a linked ``Global -> Project -> [Channel] -> Thread`` chain."""

    def __init__(
        self,
        *,
        chain: AgentSettingsChain,
        agent_scope: AgentSettingsScope,
        registry_scope: str,
        parent_state: ObjectState,
    ) -> None:
        self.chain = chain
        self.agent_scope = agent_scope
        self.scope_label = scope_label(agent_scope)
        self._hydrating = False
        self._authored_raw: dict[str, object] = {}
        super().__init__(
            _new_lazy_agent_settings(),
            scope_id=registry_scope,
            parent_state=parent_state,
        )
        self._authored_raw = {path: self.parameters.get(path) for path in agent_field_plans()}
        self.on_state_changed(self._state_changed)

    def field(self, path: str) -> AgentSettingField:
        return AgentSettingField(self, self.parameter_structure.path(path))

    def _most_specific_notification_fields(self, fields: set[str]) -> set[str]:
        """Emit declared leaf paths (e.g. ``thread.model``) instead of internal subfields of
        dataclass values (e.g. ``thread.model.text``) that are not registered parameters."""
        plans = agent_field_plans()
        normalized: set[str] = set()
        for path in fields:
            if path in plans:
                normalized.add(path)
                continue
            owner = next(
                (plan_path for plan_path in plans if path.startswith(f"{plan_path}.")),
                None,
            )
            if owner is not None:
                normalized.add(owner)
        return normalized

    def inherited_label(self, path: str) -> str:
        scope_id, _owner = self.get_provenance(path)
        return self.chain.inherited_text(scope_id)

    def apply_wire_overrides(self, overrides: Mapping[str, JsonValue]) -> None:
        """Apply Core's authored layer overrides silently without echoing a write back."""
        plans = agent_field_plans()
        self._hydrating = True
        try:
            for dotted_path, (_group, plan) in plans.items():
                raw_wire = overrides.get(dotted_path)
                target_value = (
                    None
                    if raw_wire is None
                    else FieldCodec.decode(plan.annotation, raw_wire)
                )
                if self.parameters.get(dotted_path) != target_value:
                    self.update_parameter(dotted_path, target_value)
                self._authored_raw[dotted_path] = target_value
            self.mark_saved()
        finally:
            self._hydrating = False

    def _state_changed(self, paths: set[str]) -> None:
        if self._hydrating or not paths:
            return
        plans = agent_field_plans()
        updates: dict[str, JsonValue] = {}
        for dotted_path in sorted(paths):
            if dotted_path not in plans:
                continue
            raw_value = self.parameters.get(dotted_path)
            if raw_value == self._authored_raw.get(dotted_path):
                continue
            self._authored_raw[dotted_path] = raw_value
            _group, plan = plans[dotted_path]
            updates[dotted_path] = (
                None if raw_value is None else FieldCodec.encode(raw_value, plan.annotation)
            )
        if updates:
            self.chain.emit_edits(self.agent_scope, updates)

    def close(self) -> None:
        self.off_state_changed(self._state_changed)


class AgentSettingsChain:
    """Linked ``ObjectState`` ancestry hydrated from one Core ``ScopedSettingsProjection``.

    Registers a read-only built-in defaults floor followed by one ``AgentScopeState`` per
    scope in ``projection.ancestry``, using nested ``ScopeKey`` segments under a private
    prefix so ``ObjectStateRegistry.registered_ancestors`` walks the exact ancestry chain
    without colliding with ``ToadSettings`` (``""``) or open view configurations.
    """

    def __init__(
        self,
        projection: ScopedSettingsProjection,
        on_edit: Callable[[AgentSettingsScope, dict[str, JsonValue]], None],
    ) -> None:
        self._on_edit = on_edit
        self._prefix = str(ScopeKey.of("agent_settings", f"chain{next(_CHAIN_IDS)}"))
        self._states: dict[AgentSettingsScope, AgentScopeState] = {}
        self._registry_to_scope: dict[str, AgentSettingsScope] = {}
        self._registered: list[ObjectState] = []

        defaults = GlobalAgentSettings()
        self.defaults_state = ObjectState(_new_lazy_agent_settings(), scope_id=self._prefix)
        for group in agent_group_schemas():
            group_value = getattr(defaults, group.name)
            for field_name in group.plans:
                self.defaults_state.update_parameter(
                    f"{group.name}.{field_name}", getattr(group_value, field_name)
                )
        self.defaults_state.mark_saved()
        ObjectStateRegistry.register(self.defaults_state)
        self._registered.append(self.defaults_state)

        self.scopes: tuple[AgentSettingsScope, ...] = tuple(
            AgentSettingsScope.parse(scope_id) for scope_id in projection.ancestry
        )
        parent: ObjectState = self.defaults_state
        segments: list[str] = [self._prefix]
        for index, scope in enumerate(self.scopes):
            segments.append(f"layer{index}")
            registry_scope = ScopeKey.SEPARATOR.join(segments)
            state = AgentScopeState(
                chain=self,
                agent_scope=scope,
                registry_scope=registry_scope,
                parent_state=parent,
            )
            ObjectStateRegistry.register(state)
            self._registered.append(state)
            self._states[scope] = state
            self._registry_to_scope[registry_scope] = scope
            parent = state

        self.apply_projection(projection)

    def state_for(self, scope: AgentSettingsScope) -> AgentScopeState:
        return self._states[scope]

    def apply_projection(self, projection: ScopedSettingsProjection) -> None:
        for scope in self.scopes:
            state = self._states[scope]
            state.apply_wire_overrides(projection.layers.get(scope.scope_id, {}))

    def inherited_text(self, registry_scope: str | None) -> str:
        if not registry_scope or registry_scope == self._prefix:
            return "Built-in default"
        source = self._registry_to_scope.get(registry_scope)
        if source is None:
            return "Built-in default"
        return f"Inherited from {scope_label(source)}"

    def core_scope_for_registry(self, registry_scope: str | None) -> str:
        if not registry_scope or registry_scope == self._prefix:
            return "built-in default"
        source = self._registry_to_scope.get(registry_scope)
        if source is None:
            return "built-in default"
        return source.scope_id or "global"

    def emit_edits(
        self, scope: AgentSettingsScope, updates: dict[str, JsonValue]
    ) -> None:
        self._on_edit(scope, updates)

    def close(self) -> None:
        for state in self._states.values():
            state.close()
        for state in reversed(self._registered):
            ObjectStateRegistry.unregister(state)
        self._registered.clear()
        self._states.clear()
        self._registry_to_scope.clear()


class AgentSettingsPanel(metaclass=AbstractHooksMeta):
    """Toolkit-neutral controller for the scoped ``Agent settings`` sidebar page.

    Textual's ``AgentSettingsProperties`` and Qt's ``QtAgentSettingsProperties`` inherit
    this directly, sharing scope resolution, Core load/persist round-trips, and the linked
    ``AgentSettingsChain`` while supplying only native selector + ``ObjectFormView`` hosting.
    """

    panel_spec: ClassVar[PanelSpec] = PanelSpec(
        title="Agent settings", flex=True, id="scoped-agent-settings"
    )
    panel_identity: ClassVar[object] = "scoped-agent-settings"

    _chain: AgentSettingsChain | None
    _selected_scope: AgentSettingsScope | None
    _target_scope: AgentSettingsScope
    _channel: str

    def init_agent_settings(self, app, view) -> None:
        self._settings_app = app
        self._settings_view = view
        self._chain = None
        self._selected_scope = None
        self._target_scope, self._channel = view.agent_settings_target()

    def _core_access(self) -> CoreAccess:
        access = self._settings_app.coordination_access
        root = self._settings_view.coordination_root
        observed = access.observing(root) if root is not None else access.open_current()
        return observed.core

    async def load_agent_settings(self) -> None:
        """Read the view's scoped projection from Core off the UI loop and hydrate the chain."""
        self.show_loading()
        try:
            projection = await self.run_settings_thread(
                lambda: self._core_access().call(
                    CommsAgentSettingsTool(
                        scope=self._target_scope.scope_id,
                        channel=self._channel,
                    )
                )
            )
        except CLI_FAILURES as error:
            if self.settings_panel_alive():
                self.show_unavailable(f"Agent settings unavailable: {error}")
            return
        if not self.settings_panel_alive():
            return
        self.close_agent_settings_chain()
        self._chain = AgentSettingsChain(projection, self._on_chain_edit)
        self._selected_scope = AgentSettingsScope.parse(projection.scope)
        self.show_agent_settings_chain(
            self._chain.scopes,
            self._selected_scope,
            self._chain.state_for(self._selected_scope),
        )

    def select_agent_scope(self, scope: AgentSettingsScope) -> None:
        if self._chain is None or scope == self._selected_scope:
            return
        self.finish_active_form()
        self._selected_scope = scope
        self.show_agent_scope_form(self._chain.state_for(scope))

    def _on_chain_edit(
        self, scope: AgentSettingsScope, updates: dict[str, JsonValue]
    ) -> None:
        self.schedule_settings_persist(self._persist_edits(scope, updates))

    async def _persist_edits(
        self, scope: AgentSettingsScope, updates: dict[str, JsonValue]
    ) -> None:
        try:
            projection = await self.run_settings_thread(
                lambda: self._core_access().call(
                    CommsSetAgentSettingsTool(
                        scope=scope.scope_id,
                        values=updates,
                        channel=self._channel,
                    )
                )
            )
        except CLI_FAILURES as error:
            if self.settings_panel_alive():
                self._settings_app.show_error(error, "Agent settings")
                await self.load_agent_settings()
            return
        if not self.settings_panel_alive() or self._chain is None:
            return
        self._chain.apply_projection(projection)

    def close_agent_settings_chain(self) -> None:
        if self._chain is not None:
            self._chain.close()
            self._chain = None
        self._selected_scope = None

    @abstractmethod
    def settings_panel_alive(self) -> bool: ...

    @abstractmethod
    async def run_settings_thread(self, work): ...

    @abstractmethod
    def schedule_settings_persist(self, coro: Coroutine) -> None: ...

    @abstractmethod
    def finish_active_form(self) -> None: ...

    @abstractmethod
    def show_loading(self) -> None: ...

    @abstractmethod
    def show_unavailable(self, text: str) -> None: ...

    @abstractmethod
    def show_agent_settings_chain(
        self,
        scopes: tuple[AgentSettingsScope, ...],
        selected: AgentSettingsScope,
        state: AgentScopeState,
    ) -> None: ...

    @abstractmethod
    def show_agent_scope_form(self, state: AgentScopeState) -> None: ...
