"""Typed ACP advertisements own their selection, publication and request behavior."""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from acp.exceptions import RequestError
from acp.schema import (
    SessionConfigOptionSelect,
    SessionConfigSelectGroup,
    SessionConfigSelectOption,
)
from agent_comms.acp_failure import RequestFailure
from agent_comms.declared_family import DeclaredFamily
from metaclass_registry.mro_dispatch import MroDispatch, handles


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
    option: SessionConfigOptionSelect | None = None
    label: ClassVar[str]

    @classmethod
    @abstractmethod
    def matches(cls, option: SessionConfigOptionSelect) -> bool: ...

    @classmethod
    def bind(cls, option: SessionConfigOptionSelect):
        if option.current_value not in {value.value for value in SelectChoices(option).values}:
            raise ValueError(f"ACP configuration {option.id!r} has no advertised current value")
        return cls(option)

    @property
    def available(self) -> bool:
        return self.option is not None

    @property
    def current(self) -> str:
        return self.option.current_value if self.option else ""

    @property
    def choices(self) -> tuple[SessionConfigSelectOption, ...]:
        return tuple(SelectChoices(self.option).values) if self.option else ()

    @property
    def selected(self) -> SessionConfigSelectOption | None:
        return next((choice for choice in self.choices if choice.value == self.current), None)

    def with_current(self, value: str):
        if self.option is None:
            raise ValueError(f"ACP {self.label} update arrived without an advertisement")
        return self.bind(self.option.model_copy(update={"current_value": value}))

    async def select(self, agent, value: str) -> str | None:
        if self.option is None:
            return f"This agent does not advertise {self.label} configuration"
        from toad.acp.client_session import ClientSessionRequest
        authority = ClientSessionRequest(agent, agent.session_id)
        authority.require()
        try:
            result = await agent.process.rpc.set_config_option(self.option.id, agent.session_id, value)
            authority.require()
        except RequestError as error:
            return RequestFailure.from_error(error).failure.feedback
        agent.configuration.receive(result.config_options)
        return None


class ModelConfigurationSetting(ConfigurationSetting):
    label = "model"

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


class ModeConfigurationSetting(ConfigurationSetting):
    label = "mode"

    @classmethod
    def matches(cls, option):
        return option.category == "mode"


class ConfigurationAdvertisements(MroDispatch):
    def __init__(self, selections: dict[type[ConfigurationSetting], ConfigurationSetting]) -> None:
        self.selections = selections

    @handles(SessionConfigOptionSelect)
    def selection(self, option) -> None:
        for kind in ConfigurationSetting.members_with(ConfigurationSetting):
            if kind.matches(option):
                self.selections[kind] = kind.bind(option)
                return


class AgentConfiguration:
    """Single actual advertisement owner; detached surfaces keep this same value."""
    def __init__(self, agent) -> None:
        self.agent = agent
        self.reset()

    def reset(self) -> None:
        self.selections = {kind: kind() for kind in ConfigurationSetting.members_with(ConfigurationSetting)}

    def setting[T: ConfigurationSetting](self, kind: type[T]) -> T:
        from typing import cast
        return cast(T, self.selections[kind])

    @property
    def model(self) -> ModelConfigurationSetting:
        return self.setting(ModelConfigurationSetting)

    @property
    def thinking(self) -> ThinkingConfigurationSetting:
        return self.setting(ThinkingConfigurationSetting)

    @property
    def mode(self) -> ModeConfigurationSetting:
        return self.setting(ModeConfigurationSetting)

    def receive_current_mode(self, value: str) -> None:
        self.selections[ModeConfigurationSetting] = self.mode.with_current(value)
        self.publish()

    def receive(self, options) -> None:
        if options is None:
            return
        # Official external decoder once; consumers use its guaranteed typed fields.
        selections = {kind: kind() for kind in ConfigurationSetting.members_with(ConfigurationSetting)}
        decoder = ConfigurationAdvertisements(selections)
        for option in options:
            decoder.dispatch_sync(option)
        self.selections = selections
        self.publish()

    def publish(self) -> None:
        from toad.core.events import ConfigurationChanged
        self.agent.events.publish(ConfigurationChanged())
