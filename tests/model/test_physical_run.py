"""Admission and current-resource contracts; no frontend, provider or private bus."""
from dataclasses import replace
from pathlib import Path

import pytest

from agent_comms.child_process import ProcessIdentity
from agent_comms.installer.probes.interpreter import InterpreterBuildProbe
from agent_comms.installer.runtime_resolution import RuntimeResolution
from agent_comms.storage_rules import StorageRule
from tools.physical_ui_remote import (
    AdmittedResult, FrontendIdentity, ObservedResult, PendingRun, RunObservation, RunTarget,
)


@pytest.fixture
def physical_target(tmp_path: Path) -> RunTarget:
    """Synthetic resource paths and metadata, not an application admission proof."""
    root, home, runtime = (tmp_path / name for name in ("bus", "frontend-home", "runtime"))
    for path in (root, home, runtime):
        path.mkdir()
    build = RuntimeResolution(
        core_commit="a" * 40, packages={}, interpreter=InterpreterBuildProbe().run(),
    )
    return RunTarget(root, home, runtime, build)


@pytest.fixture
def physical_observation(physical_target: RunTarget) -> RunObservation:
    target = physical_target
    return RunObservation(
        frontend=FrontendIdentity(
            ProcessIdentity.current(), target.runtime / "toad/__init__.py",
            target.runtime / "agent_comms/__init__.py", target.runtime / "textual/__init__.py",
        ),
        started_ns=1, finished_ns=2, runtime=target.runtime, home=target.home,
        config=target.config, state=target.state, data=target.data,
        database=target.state / "toad.db", palette_directory=target.palette,
        root=target.root, opened=True, storage_rule=StorageRule().within(target.root),
        saved_roots=(target.root,),
        acp_roots=(target.root,), history_regions=(), modules_checked=3,
    )


@pytest.fixture
def physical_admission(
    physical_target: RunTarget, physical_observation: RunObservation,
) -> AdmittedResult:
    return AdmittedResult(physical_observation, physical_target.build).admitted(physical_target)


def test_current_observation_cannot_substitute_for_build_admission(
    physical_target: RunTarget, physical_observation: RunObservation, physical_admission: AdmittedResult,
) -> None:
    with pytest.raises(ValueError, match="did not verify the runtime build"):
        ObservedResult(physical_observation).admitted(physical_target)
    assert physical_admission.observe(physical_target, physical_observation) == physical_observation


def test_admission_refuses_different_build_and_frontend_birth(
    physical_target: RunTarget, physical_observation: RunObservation, physical_admission: AdmittedResult,
) -> None:
    different = physical_target.build.model_copy(update={"core_commit": "b" * 40})
    with pytest.raises(ValueError):
        AdmittedResult(physical_observation, different).admitted(physical_target)
    original = physical_observation.frontend
    replacement = replace(original, process=replace(original.process, pid=original.process.pid + 1))
    with pytest.raises(ValueError, match="frontend process or module-file locations changed"):
        physical_admission.observe(physical_target, replace(physical_observation, frontend=replacement))


@pytest.mark.parametrize("field", (
    "runtime", "home", "config", "state", "data", "database", "palette_directory", "root",
))
def test_admission_does_not_cache_permission_for_changed_resources(
    field: str, tmp_path: Path, physical_target: RunTarget,
    physical_observation: RunObservation, physical_admission: AdmittedResult,
) -> None:
    current = replace(physical_observation, **{field: tmp_path / "foreign"})
    with pytest.raises(ValueError):
        physical_admission.observe(physical_target, current)


@pytest.mark.parametrize("field", ("toad_module", "core_module", "textual_module"))
def test_changed_primary_module_location_invalidates_admission(
    field: str, tmp_path: Path, physical_target: RunTarget,
    physical_observation: RunObservation, physical_admission: AdmittedResult,
) -> None:
    changed = replace(physical_observation.frontend, **{field: tmp_path / "foreign"})
    with pytest.raises(ValueError, match="frontend process or module-file locations changed"):
        physical_admission.observe(physical_target, replace(physical_observation, frontend=changed))


@pytest.mark.parametrize("field", ("saved_roots", "acp_roots"))
def test_new_saved_and_acp_roots_are_checked_after_admission(
    field: str, tmp_path: Path, physical_target: RunTarget,
    physical_observation: RunObservation, physical_admission: AdmittedResult,
) -> None:
    current = replace(physical_observation, **{field: (physical_target.root, tmp_path / "foreign")})
    with pytest.raises(ValueError, match="Foreign saved/ACP source"):
        physical_admission.observe(physical_target, current)


def test_actual_source_policy_is_checked_after_admission(
    tmp_path: Path, physical_target: RunTarget,
    physical_observation: RunObservation, physical_admission: AdmittedResult,
) -> None:
    foreign = physical_observation.storage_rule.within(tmp_path / "foreign")
    current = replace(physical_observation, storage_rule=foreign)
    with pytest.raises(ValueError):
        physical_admission.observe(physical_target, current)


def test_source_readiness_is_current_not_remembered_admission(
    physical_target: RunTarget, physical_observation: RunObservation, physical_admission: AdmittedResult,
) -> None:
    with pytest.raises(PendingRun):
        physical_admission.observe(physical_target, replace(physical_observation, opened=False))
