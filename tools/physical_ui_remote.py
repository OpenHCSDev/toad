"""Typed operations of one owned physical run, copied beside their requests.

The exec operation grants only its recorded controller's descendants debugging
access, then execs the unchanged launcher. Observation reads live source owners;
it never opens a Comms, sends input, repairs a route or traverses the heap.
"""

from abc import abstractmethod
import ctypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import pwd
import sys
import time
from typing import ClassVar

from agent_comms.child_process import ChildOutcome, ProcessIdentity
from agent_comms.launch_runtime import LaunchRuntime
from agent_comms.installer.probes.resolution import RuntimeResolutionProbe
from agent_comms.installer.runtime_resolution import RuntimeResolution
from agent_comms.storage_rules import StorageRule
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import DeclaredWireType, FieldCodec
from textual.geometry import Region
from ui_theme.wal import WalFile
from agent_comms.store_files import ExclusiveAtomicFile


class PendingRun(RuntimeError):
    """The observed startup has not acquired its source yet; no input is allowed."""


@dataclass(frozen=True)
class RunTarget:
    """Intended private resources, distinct from an observation of the app."""

    root: Path
    home: Path
    runtime: Path
    build: RuntimeResolution

    def __post_init__(self):
        self.build.interpreter.require_recorded()
        for path in (self.root, self.home, self.runtime):
            if path != path.resolve(strict=True):
                raise ValueError(f"A physical run needs canonical existing paths: {path}")
        workspace = self.home.parent
        user_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        if workspace == user_home or user_home.is_relative_to(workspace):
            raise ValueError("A physical run cannot use the real user's home as its workspace")
        if not self.root.is_relative_to(workspace) or self.root == workspace:
            raise ValueError("The copied root and private home must belong to one run workspace")
        if self.root == self.home or self.root.is_relative_to(self.home):
            raise ValueError("The copied root is separate from frontend persistence")

    @property
    def launch_runtime(self) -> LaunchRuntime:
        return LaunchRuntime.at_prefix(self.runtime)

    @property
    def palette(self) -> Path:
        return WalFile.directory({"HOME": str(self.home)})

    @property
    def config(self) -> Path:
        return self.home / "config"

    @property
    def state(self) -> Path:
        return self.home / "state"

    @property
    def data(self) -> Path:
        return self.home / "data"

    def require_resources(self, observed):
        """Current UI/source resources; build evidence belongs to AdmittedResult."""
        if observed.home != self.home or observed.runtime != self.runtime:
            raise ValueError("Post-attachment HOME/runtime differs from the run target")
        if (observed.config, observed.state, observed.data) != (self.config, self.state, self.data):
            raise ValueError("Post-attachment XDG persistence differs from the private run")
        if observed.palette_directory != self.palette:
            raise ValueError("The actual theme palette is outside the private home")
        if not observed.database.is_relative_to(self.state):
            raise ValueError("Toad's actual database is outside private state")
        if observed.root != self.root:
            raise ValueError("Core selected a foreign source")
        if not observed.opened:
            raise PendingRun("Core has not opened the intended private source")
        observed.storage_rule.require_isolated(self.root)
        for root in (*observed.saved_roots, *observed.acp_roots):
            if root != self.root:
                raise ValueError(f"Foreign saved/ACP source refuses physical input: {root}")
        return observed


@dataclass(frozen=True)
class CapturedRegion(DeclaredWireType):
    """Wire capability for Textual's final compiled Region, without copying its fields.

    The installed Region rejects subclassing; geometry remains on that existing
    type. Only this private boundary's representation lives here.
    """

    region: Region
    wire_type = tuple[int, ...]

    def to_wire(self):
        return list(self.region)

    @classmethod
    def from_wire(cls, data):
        return cls(Region(*FieldCodec.decode(cls.wire_type, data)))


@dataclass(frozen=True)
class FrontendIdentity:
    """One process birth and its primary module-file locations."""

    process: ProcessIdentity
    toad_module: Path
    core_module: Path
    textual_module: Path


@dataclass(frozen=True)
class RunObservation:
    frontend: FrontendIdentity
    started_ns: int
    finished_ns: int
    runtime: Path
    home: Path
    config: Path
    state: Path
    data: Path
    database: Path
    palette_directory: Path
    root: Path
    opened: bool
    storage_rule: StorageRule
    saved_roots: tuple[Path, ...]
    acp_roots: tuple[Path, ...]
    history_regions: tuple[CapturedRegion, ...]
    modules_checked: int


@dataclass(frozen=True)
class ProcessRetirement:
    """The existing child owner's result, qualified by the exact resource birth."""

    identity: ProcessIdentity
    outcome: ChildOutcome


class PhysicalResult(DeclaredFamily, affix="Result"):
    def require(self):
        return self

    def admitted(self, target: RunTarget) -> AdmittedResult:
        raise ValueError("This physical operation did not verify the runtime build")

    def observation(self) -> RunObservation:
        raise ValueError("This physical operation did not observe an application")

    def process(self) -> ProcessIdentity:
        raise ValueError("This physical operation did not exec a frontend")


@dataclass(frozen=True)
class ObservedResult(PhysicalResult):
    value: RunObservation

    def observation(self) -> RunObservation:
        return self.value


@dataclass(frozen=True)
class AdmittedResult(ObservedResult):
    """Build evidence for one frontend birth, not a fresh hash on every UI read."""

    build: RuntimeResolution

    def admitted(self, target: RunTarget) -> AdmittedResult:
        target.build.require_runtime(self.build)
        target.require_resources(self.value)
        return self

    def observe(self, target: RunTarget, current: RunObservation) -> RunObservation:
        if current.frontend != self.value.frontend:
            raise ValueError("The admitted frontend process or module-file locations changed")
        # Dynamic persistence and every saved/ACP root still precede each input.
        return target.require_resources(current)


@dataclass(frozen=True)
class ExecResult(PhysicalResult):
    identity: ProcessIdentity
    debugger: ProcessIdentity

    def process(self) -> ProcessIdentity:
        return self.identity


@dataclass(frozen=True)
class StoppedResult(PhysicalResult):
    root: Path


@dataclass(frozen=True)
class PendingResult(PhysicalResult):
    detail: str

    def require(self):
        raise PendingRun(self.detail)

    def observation(self) -> RunObservation:
        self.require()


@dataclass(frozen=True)
class FailedResult(PhysicalResult):
    error: str
    detail: str

    def require(self):
        raise RuntimeError(f"Physical operation failed: {self.error}: {self.detail}")

    def observation(self) -> RunObservation:
        self.require()

    def process(self) -> ProcessIdentity:
        self.require()


class PhysicalOperation(DeclaredFamily, affix="Operation"):
    metadata_bytes: ClassVar[int] = 65536
    source_bytes: ClassVar[int] = 256 << 10
    timeout: ClassVar[float] = 10.0

    @abstractmethod
    def execute(self, directory: Path) -> None: ...

    @classmethod
    def publish(cls, path: Path, value: object) -> None:
        encoded = json.dumps(FieldCodec.encode(value), ensure_ascii=False, allow_nan=False).encode()
        if len(encoded) > cls.metadata_bytes:
            raise ValueError("Physical metadata exceeds its byte bound")
        ExclusiveAtomicFile(path).write_bytes(encoded)

    @classmethod
    def read_result(cls, path: Path) -> PhysicalResult:
        with path.open("rb") as source:
            raw = source.read(cls.metadata_bytes + 1)
        if len(raw) > cls.metadata_bytes:
            raise ValueError("Oversize physical result")
        return FieldCodec.decode(PhysicalResult, FieldCodec.parse(raw.decode()))

    @classmethod
    def execute_file(cls, script: Path) -> None:
        directory = script.parent
        result = directory / "result.json"
        try:
            with script.with_suffix(".json").open("rb") as source:
                raw = source.read(cls.metadata_bytes + 1)
            if len(raw) > cls.metadata_bytes:
                raise ValueError("Oversize physical request")
            operation = FieldCodec.decode(cls, FieldCodec.parse(raw.decode()))
            operation.execute(directory)
        except PendingRun as error:
            cls.publish(result, PendingResult(str(error)[:2048]))
        except BaseException as error:
            cls.publish(directory / "error.json", FailedResult(type(error).__name__, str(error)[:2048]))


@dataclass(frozen=True)
class ExecOperation(PhysicalOperation):
    """One new child, not an arbitrary existing trace target or global policy."""

    target: RunTarget
    debugger: ProcessIdentity
    arguments: tuple[str, ...]
    PR_SET_PTRACER: ClassVar[int] = 0x59616D61  # Linux's declared prctl ABI.

    def execute(self, directory: Path) -> None:
        if not self.arguments or not self.debugger.alive():
            raise ValueError("Exec needs its original living controller and command")
        if Path.home().resolve() != self.target.home:
            raise ValueError("st changed HOME before frontend exec")
        prctl = ctypes.CDLL(None, use_errno=True).prctl
        prctl.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong)
        prctl.restype = ctypes.c_int
        if prctl(self.PR_SET_PTRACER, self.debugger.pid, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Cannot admit this controller's debugger descendants")
        self.publish(directory / "result.json", ExecResult(ProcessIdentity.current(), self.debugger))
        os.execvpe(self.arguments[0], self.arguments, os.environ)


@dataclass(frozen=True)
class ObserveOperation(PhysicalOperation):
    target: RunTarget
    identity: ProcessIdentity
    tools: Path

    def observed_result(self, observed: RunObservation) -> PhysicalResult:
        return ObservedResult(observed)

    def execute(self, directory: Path) -> None:
        started = time.monotonic_ns()
        if ProcessIdentity.current() != self.identity:
            raise ValueError("Post-attachment frontend incarnation changed")
        if Path.home().resolve() != self.target.home:
            raise ValueError("Post-attachment HOME is not private")
        # The existing reviewed validator remains the single module-location policy.
        # The temporary tool import path is retired before inspecting application state.
        previous = sys.path[:]
        try:
            sys.path.insert(0, str(self.tools))
            from performance.history_capture_remote import require_modules
        finally:
            sys.path[:] = previous
        import agent_comms
        import textual
        import toad
        from agent_comms.acp_extension import CoordinationChangedUpdate
        from metaclass_registry.mro_dispatch import handles
        from toad.acp.agent import Agent
        from toad.agent_binding import NoAgentConnection
        from toad.app import ToadApp
        from textual._context import NoActiveAppError
        from textual.app import ScreenStackError
        from toad.core.projection import MroProjection
        from toad.widgets.history_anchor import HistoryWindow
        from xdg_base_dirs import xdg_config_home, xdg_data_home, xdg_state_home

        class AcpRoots(MroProjection[tuple[Path, ...]]):
            """Decode foreign running-UI connections once, without guessing readiness."""

            @handles(object)
            def unknown(self, value):
                raise ValueError(f"Unadmitted ACP metadata type: {type(value).__name__}")

            @handles(type(None))
            def pending(self, value):
                raise PendingRun("A bound ACP has not published its coordination root")

            @handles(NoAgentConnection)
            def unbound(self, value):
                return ()

            @handles(Agent)
            def bound(self, value):
                return self.project_value(value.coordination)

            @handles(CoordinationChangedUpdate)
            def coordinated(self, value):
                return (Path(value.wire_root).resolve(),)

        try:
            app = ToadApp.running_app()
            screen = app.screen
        except (NoActiveAppError, ScreenStackError) as error:
            raise PendingRun("No sole running Toad application with a screen yet") from error
        checked = require_modules(self.target.runtime)
        access = app.coordination_access
        root = access.selection.root
        observation = access.observation
        opened = observation.observes(root)
        if not opened:
            raise PendingRun("Core has not opened the intended private source")
        storage_rule = observation.service.registry.storage_rule
        sessions = app.session_navigation
        saved = tuple(Path(source).resolve() for entry in sessions.members
                      for source, _identity in (*entry.original_threads(sessions), *entry.original_channels()))
        decoder = AcpRoots()
        acp = tuple(source for process in dict.fromkeys(sessions.processes)
                    for agent in (process.agent, *(session.agent for session in process.sessions))
                    for source in decoder.project_value(agent))
        # This is geometry of actually published history windows, not a guess
        # from sidebar separators that may also occur inside a user's message.
        regions = tuple(CapturedRegion(region) for window in screen.query(HistoryWindow)
                        for region in (window.published_content_region,) if region is not None)
        frontend = FrontendIdentity(
            self.identity, Path(toad.__file__).resolve(), Path(agent_comms.__file__).resolve(),
            Path(textual.__file__).resolve(),
        )
        observed = RunObservation(
            frontend, started, time.monotonic_ns(), Path(sys.prefix).resolve(),
            Path.home().resolve(), xdg_config_home().resolve(), xdg_state_home().resolve(),
            xdg_data_home().resolve(), app.tab_order._db.path.resolve(),
            app.colours.wal_directory.resolve(), root,
            opened, storage_rule, saved, acp, regions, checked,
        )
        self.target.require_resources(observed)
        self.publish(directory / "result.json", self.observed_result(observed))


@dataclass(frozen=True)
class AdmitOperation(ObserveOperation):
    """Full disk-artifact verification at entry and successful retirement only."""

    def observed_result(self, observed: RunObservation) -> PhysicalResult:
        build = RuntimeResolutionProbe(
            self.target.build.core_commit, self.target.build.wheel_inputs()
        ).run()
        return AdmittedResult(observed, build).admitted(self.target)


@dataclass(frozen=True)
class StopRootOperation(PhysicalOperation):
    """Stop only the private copy, in its own declared runtime; retain its files."""

    target: RunTarget

    def execute(self, directory: Path) -> None:
        if LaunchRuntime.running().prefix != self.target.runtime:
            raise ValueError("Private-copy shutdown must run in its declared runtime")
        from agent_comms.comms import wire
        from agent_comms.launch_root import LaunchRoot
        from agent_comms.registry_document import RosterVisibility

        with LaunchRoot.from_path(self.target.root).selected():
            copied = wire()
            for thread in copied.registry.snapshot().visible_threads(RosterVisibility(archived=True)):
                copied.owners.stop(thread.name)
        self.publish(directory / "result.json", StoppedResult(self.target.root))


# Normal imports define the family. A controller-bound module filename selects
# only that immutable copy's adjacent request, including under remote_exec.
_source = Path(__file__)
if _source.with_suffix(".json").is_file():
    PhysicalOperation.execute_file(_source)
