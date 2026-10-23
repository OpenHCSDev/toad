"""A nominal projection returns one leaf's result without replacing its input."""

from dataclasses import dataclass

import pytest
from agent_comms.mro_dispatch import handles

from toad.core.projection import MroProjection


@dataclass(frozen=True)
class Value:
    text: str


class SpecificValue(Value):
    pass


@dataclass(frozen=True)
class Rendering:
    text: str


@pytest.mark.parametrize("override", [False, True])
def test_projection_returns_the_specific_result_and_forwards_context(override: bool) -> None:
    selected: list[str] = []

    class TextProjection(MroProjection[Rendering]):
        @handles(Value)
        def base(self, value: Value, prefix: str, *, suffix: str) -> Rendering:
            selected.append("base")
            return Rendering("base")

        @handles(SpecificValue)
        def specific(self, value: SpecificValue, prefix: str, *, suffix: str) -> Rendering:
            selected.append("specific")
            return Rendering(f"{prefix}{value.text}{suffix}")

    class OverriddenProjection(TextProjection):
        @handles(SpecificValue)
        def specific(self, value: SpecificValue, prefix: str, *, suffix: str) -> Rendering:
            selected.append("override")
            return Rendering(f"{prefix}override:{value.text}{suffix}")

    projection = OverriddenProjection() if override else TextProjection()
    value = SpecificValue("original")
    result = projection.project(value, "[", suffix="]")

    assert result == Rendering("[override:original]" if override else "[original]")
    assert selected == ["override" if override else "specific"]
    assert value == SpecificValue("original")


def test_projection_preserves_a_none_result_from_a_side_effect_handler() -> None:
    selected: list[str] = []

    class RecordingProjection(MroProjection[None]):
        @handles(Value)
        def record(self, value: Value) -> None:
            selected.append(value.text)

    assert RecordingProjection().project(Value("recorded")) is None
    assert selected == ["recorded"]


def test_projection_without_a_declared_handler_raises_stop_iteration() -> None:
    with pytest.raises(StopIteration):
        MroProjection[Rendering]().project(Value("unhandled"))


def test_unavailable_owner_projection_does_not_supply_a_load_plan():
    from agent_comms.thread_presentation import UnavailableThreadOwnerBinding
    from toad.owner_preparation import ExistingOwnerPlan

    plan = ExistingOwnerPlan.from_binding(UnavailableThreadOwnerBinding())
    assert not plan.available
    with pytest.raises(ValueError, match="live owner binding"):
        plan.require_plan()


def test_live_owner_projection_retains_the_exact_load_binding():
    from agent_comms.child_process import ProcessIdentity
    from agent_comms.session_load import ExistingSessionLoadPlan
    from agent_comms.thread_identity import OwnerIdentity, RecordedThreadIncarnation
    from agent_comms.thread_presentation import LiveThreadOwnerBinding
    from toad.owner_preparation import ExistingOwnerPlan

    binding = LiveThreadOwnerBinding(
        OwnerIdentity(RecordedThreadIncarnation("projection-owner", 123.0), 2),
        ProcessIdentity(1, 1),
    )
    plan = ExistingOwnerPlan.from_binding(binding)
    assert plan.available
    assert plan.require_plan() == ExistingSessionLoadPlan(binding)
