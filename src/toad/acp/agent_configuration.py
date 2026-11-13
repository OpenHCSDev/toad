"""Typed ACP advertisements own their selection, publication and request behavior."""
from __future__ import annotations

from dataclasses import dataclass, field, make_dataclass
from typing import Annotated, ClassVar, cast

from acp.exceptions import RequestError
from acp.schema import (
    SessionConfigOptionBoolean,
    SessionConfigOptionSelect,
    SessionConfigSelectGroup,
    SessionConfigSelectOption,
)
from agent_comms.execution.acp_failure import RequestFailure
from agent_comms.nominal.declared_family import DeclaredFamily
from formbridge.forms.declared_fields import DeclaredMetadata
from metaclass_registry.mro_dispatch import MroDispatch, handles
from objectstate import ObjectState
from python_introspect import FieldLabel

from python_introspect.choices import LabelledChoices
from toad.acp.client_session import ClientSessionRequest
from toad.core.configuration_events import ChangeConfiguration, ChangeModel
from toad.core.events import ConfigurationChanged
from toad.db import DB
from toad.input_decision import InputAccepted, InputDecision, ModelSelectionRequired


class SelectChoices(MroDispatch):
    """Flatten only the SDK's decoded external flat/group variants."""
    def __init__(self, option: SessionConfigOptionSelect) -> None:
        self.values: list[SessionConfigSelectOption] = []
        for value in option.options:
            self.dispatch_sync(value)

    @handles(SessionConfigSelectOption)
    def choice(self, value) -> None:
        self.values.append(value)

    @handles(SessionConfigSelectGroup)
    def group(self, value) -> None:
        self.values.extend(value.options)


@dataclass(frozen=True)
class ConfigurationSetting(DeclaredFamily, affix="ConfigurationSetting"):
    option: SessionConfigOptionSelect | SessionConfigOptionBoolean | None = None
    label: ClassVar[str] = "setting"
    show_provider: ClassVar[bool] = False

    @property
    def picker_title(self) -> str:
        return self.option.name if self.option else self.label

    def picker_settings(self) -> tuple[ConfigurationSetting, ...]:
        return (self,) if self.available else ()

    async def recent_choices(self, scope: str) -> list[str]:
        return []

    def selection_event(self, value: str | bool):
        return ChangeConfiguration(self.option.id, value)

    @classmethod
    def matches(cls, option: SessionConfigOptionSelect) -> bool:
        return False

    @classmethod
    def bind(cls, option: SessionConfigOptionSelect):
        if option.current_value not in {value.value for value in SelectChoices(option).values}:
            raise ValueError(f"ACP configuration {option.id!r} has no advertised current value")
        return cls(option)

    @property
    def available(self) -> bool:
        return self.option is not None

    @property
    def current(self) -> str | bool:
        return self.option.current_value if self.option else ""

    @property
    def choices(self) -> tuple[SessionConfigSelectOption, ...]:
        return tuple(SelectChoices(self.option).values) if self.option else ()

    @property
    def selected(self) -> SessionConfigSelectOption | None:
        return next((choice for choice in self.choices if choice.value == self.current), None)

    @property
    def annotation(self) -> object:
        return Annotated[str, AdvertisedChoices(self), FieldLabel(self.picker_title), (self.option.description or "") if self.option else ""]

    def with_current(self, value: str):
        if self.option is None:
            raise ValueError(f"ACP {self.label} update arrived without an advertisement")
        return self.bind(self.option.model_copy(update={"current_value": value}))

    async def select(self, agent, value: str | bool) -> str | None:
        if self.option is None:
            return f"This agent does not advertise {self.label} configuration"
        authority = ClientSessionRequest(agent, agent.session_id)
        authority.require()
        try:
            result = await agent.process.rpc.set_config_option(self.option.id, agent.session_id, value)
            authority.require()
        except RequestError as error:
            return RequestFailure.from_error(error).failure.feedback
        agent.configuration.receive(result.config_options)
        return None


@dataclass(frozen=True)
class AdvertisedSetting:
    """The original advertised setting behind a projected form field."""
    setting: ConfigurationSetting


@dataclass(frozen=True)
class AdvertisedChoices(AdvertisedSetting, LabelledChoices, DeclaredMetadata):
    def labelled_choices(self) -> tuple[tuple[str, object], ...]:
        return tuple((choice.name, choice.value) for choice in self.setting.choices)

    def declares(self):
        yield from type(self.setting).__mro__[:-1]
        yield from super().declares()


class BooleanConfigurationSetting(ConfigurationSetting):
    @classmethod
    def bind(cls, option: SessionConfigOptionBoolean):
        return cls(option)

    @property
    def annotation(self) -> object:
        return Annotated[bool, AdvertisedSetting(self), FieldLabel(self.picker_title), self.option.description or ""]


class ModelConfigurationSetting(ConfigurationSetting):
    label = "model"
    show_provider = True

    def picker_settings(self) -> tuple[ConfigurationSetting, ...]:
        # Provider setup remains reachable before a model is advertised.
        return (self,)

    async def recent_choices(self, scope: str) -> list[str]:
        return await DB().recent_models(scope)

    def selection_event(self, value: str):
        return ChangeModel(value)

    @property
    def input_decision(self) -> InputDecision:
        return ModelSelectionRequired() if self.requires_selection else InputAccepted()

    @property
    def requires_selection(self) -> bool:
        """No advertised model can run: Core's empty catalogue is provider setup state.

        An unset current value beside advertised models is a thread running its
        runtime's default model, which sends like any other."""
        return self.available and not self.choices

    @property
    def choices(self) -> tuple[SessionConfigSelectOption, ...]:
        # The advertised empty current value is setup state, not a model the
        # user can select. The existing provider action remains reachable.
        return tuple(choice for choice in super().choices if choice.value)

    @classmethod
    def matches(cls, option):
        return option.category == "model" or option.id == "model"


class ThinkingConfigurationSetting(ConfigurationSetting):
    label = "thinking-level"

    @classmethod
    def matches(cls, option):
        return option.category == "thought_level" or option.id == "thinking_level"


class ServiceTierConfigurationSetting(ConfigurationSetting):
    label = "service tier"

    @classmethod
    def matches(cls, option):
        return option.category == "service_tier" or option.id == "service_tier"


class ModeConfigurationSetting(ConfigurationSetting):
    label = "mode"

    @classmethod
    def matches(cls, option):
        return option.category == "mode"


class ConfigurationAdvertisements(MroDispatch):
    def __init__(self, selections: dict[str, ConfigurationSetting]) -> None:
        self.selections = selections

    @handles(SessionConfigOptionSelect)
    def selection(self, option) -> None:
        kinds = tuple(kind for kind in ConfigurationSetting.members_with(ConfigurationSetting)
                      if kind.matches(option))
        kind, = kinds or (ConfigurationSetting,)
        self.add(kind.bind(option))

    @handles(SessionConfigOptionBoolean)
    def boolean(self, option) -> None:
        self.add(BooleanConfigurationSetting.bind(option))

    def add(self, setting: ConfigurationSetting) -> None:
        key = setting.option.id
        if key in self.selections:
            raise ValueError(f"ACP configuration id {key!r} is advertised twice")
        self.selections[key] = setting


class AgentConfiguration:
    """Single actual advertisement owner; detached surfaces keep this same value."""
    def __init__(self, agent) -> None:
        self.agent = agent
        self.reset()

    def reset(self) -> None:
        self.selections: dict[str, ConfigurationSetting] = {}

    def setting[T: ConfigurationSetting](self, kind: type[T]) -> T:
        matches = tuple(setting for setting in self.selections.values()
                        if isinstance(setting, kind))
        selected, = matches or (kind(),)
        return cast(T, selected)

    def named(self, key: str) -> ConfigurationSetting:
        return self.selections[key]

    def editing(self) -> ObjectState:
        """An editable projection; every field retains its exact advertisement and writer."""
        return self.editing_settings(self.picker_settings)

    def editing_settings(self, settings: tuple[ConfigurationSetting, ...]) -> ObjectState:
        """Project original settings without adding fields the source did not advertise."""
        declarations = [
            (f"option_{index}", setting.annotation, field(default=setting.current))
            for index, setting in enumerate(settings)
        ]
        return ObjectState(make_dataclass("SessionConfiguration", declarations)())

    @property
    def model(self) -> ModelConfigurationSetting:
        return self.setting(ModelConfigurationSetting)

    @property
    def thinking(self) -> ThinkingConfigurationSetting:
        return self.setting(ThinkingConfigurationSetting)

    @property
    def mode(self) -> ModeConfigurationSetting:
        return self.setting(ModeConfigurationSetting)

    @property
    def picker_settings(self) -> tuple[ConfigurationSetting, ...]:
        model = self.model
        return (*model.picker_settings(),
                *(setting for setting in self.selections.values() if setting is not model))

    def receive_current_mode(self, value: str) -> None:
        self.selections[self.mode.option.id] = self.mode.with_current(value)
        self.publish()

    def receive(self, options) -> None:
        if options is None:
            return
        # Official external decoder once; consumers use its guaranteed typed fields.
        selections: dict[str, ConfigurationSetting] = {}
        decoder = ConfigurationAdvertisements(selections)
        for option in options:
            decoder.dispatch_sync(option)
        self.selections = selections
        self.publish()

    def publish(self) -> None:
        self.agent.events.publish(ConfigurationChanged())
