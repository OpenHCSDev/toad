from dataclasses import dataclass

from toad.core.link_context_changed import CoreEvent


@dataclass(frozen=True)
class ChangeModel(CoreEvent):
    model_id: str


@dataclass(frozen=True)
class ChangeConfiguration(CoreEvent):
    setting: str
    value: str | bool
