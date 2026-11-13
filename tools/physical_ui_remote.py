"""Typed operations of one owned physical run, copied beside their requests.

Startup owns one inherited request connection and the installed Python entrypoint.
The controller submits only typed observation packets, applied on Textual's loop.
No attachment, debugger permission, code injection or signal handler is used.
"""

import importlib.machinery
import json
import os
import pwd
import sys
import time
from abc import abstractmethod
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from functools import cache, partial
from importlib.metadata import distribution
from multiprocessing.connection import Connection
from pathlib import Path
from threading import Thread
from types import ModuleType
from typing import ClassVar, Self

# Only a newly launched program adds its frozen dependency directory. An
# observation packet cannot change import paths inside an existing frontend.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))

from agent_comms.acp_extension import CoordinationChangedUpdate
from agent_comms.execution.child_process import (
    ChildOutcome,
    ProcessIdentity,
)
from agent_comms.execution.launch_runtime import LaunchRuntime
from agent_comms.installer.interpreter_operation import RuntimeProbe
from agent_comms.installer.runtime_resolution import RuntimeResolution, ToadPackage
from agent_comms.installer.runtime_stack import Extendable
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import DeclaredWireType, FieldCodec
from agent_comms.projects.storage_rules import StorageRule
from agent_comms.storage.store_files import ExclusiveAtomicFile
from metaclass_registry.mro_dispatch import handles
from pydantic import JsonValue
from textual.geometry import Region
from ui_theme.wal import WalFile

from toad.acp.agent import Agent
from toad.agent_binding import NoAgentConnection
from toad.core.projection import MroProjection
from toad.tab_identity import TabIdentity


class PendingRun(RuntimeError):
    """The observed startup has not acquired its source yet; no input is allowed."""


@dataclass(frozen=True)
class RunResources(Extendable):
    """Intended private resources, distinct from an observation of the app."""

    root: Path
    home: Path
    runtime: Path

    def __post_init__(self):
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

    def require_build(self, actual: RuntimeResolution) -> None:
        raise ValueError("An installed resource observation does not certify a candidate build")

    def require_resources(self, observed):
        """Current UI/source resources, independent of candidate build evidence."""
        if observed.home != self.home or observed.runtime != self.runtime:
            raise ValueError("Observed HOME/runtime differs from the run target")
        if (observed.config, observed.state, observed.data) != (self.config, self.state, self.data):
            raise ValueError("Observed XDG persistence differs from the private run")
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
class CapturedResponse:
    """An active reply's source text and last published native placement."""

    region: CapturedRegion
    text: str


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
    history_published: bool
    modules_checked: int
    agent_ready: bool = False
    turn_busy: bool = False
    responses: tuple[CapturedResponse, ...] = ()
    composer_focused: bool = False
    composer_regions: tuple[CapturedRegion, ...] = ()
    selected_tabs: tuple[TabIdentity, ...] = ()


@dataclass(frozen=True)
class ProcessRetirement:
    """The existing child owner's result, qualified by the exact resource birth."""

    identity: ProcessIdentity
    outcome: ChildOutcome


class PhysicalResult(DeclaredFamily, affix="Result"):
    def require(self):
        return self

    def admitted(self, target: RunResources) -> Self:
        raise ValueError("This physical operation did not verify the runtime build")

    def require_build(self) -> RuntimeResolution:
        raise ValueError("This observation carries no candidate build proof")

    def require_origins(self, original: InstalledResult) -> None:
        raise ValueError("This result did not observe installed executable and package origins")

    def observation(self) -> RunObservation:
        raise ValueError("This physical operation did not observe an application")

    def process(self) -> ProcessIdentity:
        raise ValueError("This physical operation did not start a frontend")


@dataclass(frozen=True)
class ObservedResult(PhysicalResult):
    value: RunObservation

    def observation(self) -> RunObservation:
        return self.value

    def observe(self, target: RunResources, current: RunObservation) -> RunObservation:
        if current.frontend != self.value.frontend:
            raise ValueError("The admitted frontend process or module-file locations changed")
        # Dynamic persistence and every saved/ACP root still precede each input.
        return target.require_resources(current)

    def finish(self, target: RunResources, current: PhysicalResult) -> None:
        self.observe(target, current.observation())


@dataclass(frozen=True)
class InstalledResult(ObservedResult):
    """Actual installed origins, not interpreter or candidate byte verification."""

    python_executable: Path
    native_executable: Path
    packages: JsonValue

    def finish(self, target: RunResources, current: PhysicalResult) -> None:
        super().finish(target, current)
        current.require_origins(self)

    def require_origins(self, original: InstalledResult) -> None:
        if (self.python_executable != original.python_executable
                or self.native_executable != original.native_executable
                or self.packages != original.packages):
            raise ValueError("Installed executable or package origins changed during the run")


@dataclass(frozen=True)
class StartedResult(PhysicalResult):
    identity: ProcessIdentity
    controller: ProcessIdentity

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
        except Exception as error:
            cls.publish(directory / "error.json", FailedResult(type(error).__name__, str(error)[:2048]))


@dataclass(frozen=True)
class StartOperation(PhysicalOperation):
    """Instrument a new Python frontend at startup, never an existing process."""

    target: RunResources
    controller: ProcessIdentity
    arguments: tuple[str, ...]
    descriptor: int

    def execute(self, directory: Path) -> None:
        if not self.arguments or not self.controller.alive() or self.descriptor < 3:
            raise ValueError("Startup needs its living controller, entrypoint and inherited connection")
        if Path.home().resolve() != self.target.home:
            raise ValueError("st changed HOME before frontend startup")
        if LaunchRuntime.running().prefix != self.target.runtime:
            raise ValueError("Frontend startup must use its declared runtime")
        entrypoint = Path(self.arguments[0]).resolve(strict=True)
        if not entrypoint.is_relative_to(self.target.runtime):
            raise ValueError("The instrumented entrypoint is outside the declared runtime")
        (declared,) = distribution(ToadPackage.distribution).entry_points.select(
            group="console_scripts", name=entrypoint.name,
        )
        os.set_inheritable(self.descriptor, False)
        with Connection(self.descriptor, writable=False) as requests:
            # This thread owns no UI state and never wakes periodically. Its
            # private pipe closes with this frontend/controller lifetime.
            reader = Thread(target=self.serve, args=(requests, directory.parent), daemon=True)
            reader.start()
            self.publish(directory / "result.json", StartedResult(ProcessIdentity.current(), self.controller))
            sys.argv = list(self.arguments)
            # Keep this declaration module alive while the installed entrypoint
            # runs; replacing __main__ would change the codec's type namespace.
            with self.startup_observed(directory):
                declared.load()()

    @contextmanager
    def startup_observed(self, directory: Path):
        """Optional launch-time instrumentation shares the entrypoint lifetime."""
        yield

    def answer_observation(self, packet: Path) -> None:
        """Runs on the frontend's message loop, called by this startup's request reader."""
        ObserveOperation.execute_file(packet)

    def serve(self, requests: Connection, output: Path) -> None:
        while True:
            try:
                raw = requests.recv_bytes(self.metadata_bytes)
            except EOFError:
                return
            packet = FieldCodec.decode(Path, FieldCodec.parse(raw.decode()))
            if (not packet.is_absolute() or packet != packet.resolve(strict=True)
                    or not packet.is_relative_to(output / "operations")
                    or packet != ObserveOperation.packet_path(packet.parent)):
                raise ValueError("Observation packet is outside this startup's operation directory")
            from textual._context import NoActiveAppError

            from toad.app import ToadApp

            try:
                app = ToadApp.running_app()
                if not app.is_running:
                    raise PendingRun("The frontend message loop has not started")
                # The existing decoder admits only ObserveOperation descendants;
                # a stop/start packet cannot execute through this read-only pipe.
                app.call_from_thread(self.answer_observation, packet)
            except (NoActiveAppError, PendingRun) as error:
                self.publish(packet.parent / "result.json", PendingResult(str(error)[:2048]))
            except Exception as error:
                self.publish(packet.parent / "error.json", FailedResult(type(error).__name__, str(error)[:2048]))


class MeasuredStartOperation(StartOperation):
    """Frame measurement is installed by the application's one-shot startup hook.

    The same capability composes with installed observation and strict candidate
    admission. It adds no write operation to the running observation connection.
    """

    @contextmanager
    def startup_observed(self, directory: Path):
        from toad.application_lifetime import ApplicationLifetime

        with super().startup_observed(directory), ExitStack() as cleanup:
            ApplicationLifetime.observe_next_start(partial(self.measure, directory, cleanup))
            yield

    def answer_observation(self, packet: Path) -> None:
        """An observation is this tool's work on the frontend's loop, never a frame of Toad's.

        The pause opens on the loop, so time a real callback holds the loop while the request
        queues behind it stays measured.
        """
        from tools.performance.frame_meter import measuring_pause

        with measuring_pause():
            super().answer_observation(packet)

    def measure(self, directory: Path, cleanup: ExitStack, lifetime) -> None:
        from tools.performance.frame_meter import install

        # install resolves and validates every target before changing any hook;
        # its returned closer restores them and publishes bounded output.
        cleanup.callback(install(
            expected_pid=os.getpid(), seconds=240,
            output=directory.parent / "frame-meter.json",
            max_records=200000, max_bytes=16 << 20,
        ))


@dataclass(frozen=True)
class AcpObservation:
    roots: tuple[Path, ...]
    ready: bool = False
    busy: bool = False


class AcpObservationDecoder(MroProjection[AcpObservation]):
    """One foreign-connection decoder, not a new handler class per observation."""

    @handles(object)
    def unknown(self, value):
        raise ValueError(f"Unadmitted ACP metadata type: {type(value).__name__}")

    @handles(type(None))
    def pending(self, value):
        raise PendingRun("A bound ACP has not published its coordination root")

    @handles(NoAgentConnection)
    def unbound(self, value):
        return AcpObservation(())

    @handles(Agent)
    def bound(self, value):
        source = self.project_value(value.coordination)
        return AcpObservation(source.roots, value.ready, value.current_turn.busy)

    @handles(CoordinationChangedUpdate)
    def coordinated(self, value):
        return AcpObservation((Path(value.wire_root).resolve(),))


@dataclass(frozen=True)
class ObserveOperation(PhysicalOperation):
    target: RunResources
    identity: ProcessIdentity

    @classmethod
    def packet_path(cls, directory: Path) -> Path:
        """The read-only observation protocol owns its one packet filename."""
        return directory / "request.json"

    @staticmethod
    @cache
    def resolved_location(location: str) -> Path:
        """A loaded module's location resolves once per process: it runs on the frontend's loop,
        and resolving every toad, textual and agent_comms location on each observation took
        about 60 ms, which the frame meter then had to censor as the harness's own pause."""
        return Path(location).resolve(strict=True)

    def require_modules(self, packages: tuple[ModuleType, ...]) -> int:
        """Observe foreign ModuleSpec origins through this startup's validator.

        Locations establish provenance, not hashes of already-loaded code.
        Namespace packages must supply every owned search location.
        """
        runtime = self.target.runtime
        package_names = frozenset(package.__name__ for package in packages)
        checked = 0
        for name, module in tuple(sys.modules.items()):
            if name.partition('.')[0] not in package_names:
                continue
            spec = module.__spec__  # foreign Python module boundary
            if not isinstance(spec, importlib.machinery.ModuleSpec):
                raise RuntimeError(f'Loaded package has no ModuleSpec: {name[:160]}')
            locations = ((spec.origin,) if spec.has_location else
                         tuple(spec.submodule_search_locations or ()))
            if not locations:
                raise RuntimeError(f'Loaded package has no owned locations: {name[:160]}')
            for location in locations:
                resolved = self.resolved_location(location)
                if not resolved.is_relative_to(runtime):
                    raise RuntimeError(f'Loaded package outside approved runtime: {name[:160]} {str(resolved)[:384]}')
            checked += 1
        if not checked:
            raise RuntimeError('No loaded runtime packages to observe')
        return checked

    def observed_result(self, observed: RunObservation, directory: Path) -> PhysicalResult:
        return ObservedResult(observed)

    def execute(self, directory: Path) -> None:
        started = time.monotonic_ns()
        if ProcessIdentity.current() != self.identity:
            raise ValueError("Observed frontend incarnation changed")
        if Path.home().resolve() != self.target.home:
            raise ValueError("Observed HOME is not private")
        import agent_comms
        import textual
        from textual._context import NoActiveAppError
        from textual.app import ScreenStackError
        from xdg_base_dirs import xdg_config_home, xdg_data_home, xdg_state_home

        import toad
        from toad.app import ToadApp
        from toad.live_output import ResponseStream
        from toad.widgets.conversation import Conversation
        from toad.widgets.history_anchor import HistoryWindow
        from toad.widgets.prompt import PromptTextArea

        try:
            app = ToadApp.running_app()
            screen = app.screen
        except (NoActiveAppError, ScreenStackError) as error:
            raise PendingRun("No sole running Toad application with a screen yet") from error
        checked = self.require_modules((toad, textual, agent_comms))
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
        decoder = AcpObservationDecoder()
        acp_states = tuple(decoder.project_value(agent)
                           for process in dict.fromkeys(sessions.processes)
                           for agent in (process.agent, *(session.agent for session in process.sessions)))
        acp = tuple(source for state in acp_states for source in state.roots)
        # This is geometry of actually published history windows, not a guess
        # from sidebar separators that may also occur inside a user's message.
        regions = tuple(CapturedRegion(region) for window in screen.query(HistoryWindow)
                        for region in window.published_viewport.regions())
        histories = tuple(history for window in screen.query(HistoryWindow)
                          for _shown in window.published_viewport.regions()
                          for history in window.histories)
        # Decode the installed frontend at this read-only boundary. Only the
        # current live ResponseStream supplies reply text: not a user-input
        # echo, a ThoughtStream, a saved row or an earlier completed notice.
        published = screen._compositor._published_map
        responses = tuple(
            CapturedResponse(
                CapturedRegion(placement.content_region.intersection(placement.clip)),
                block.body.text,
            )
            for view in screen.query(Conversation) if view.turns.owner.busy
            for stream in (view.output.streams.get(ResponseStream),) if stream is not None
            for block in (stream.block,) if block is not None
            for placement in (published.get(block.body),) if placement is not None
        )
        # The pager's original publication state also supplies the footer's
        # saved-history availability. Agent status is an independent fact.
        history_published = bool(histories) and all(
            history.state.coverage.retained_through(history) for history in histories)
        frontend = FrontendIdentity(
            self.identity, Path(toad.__file__).resolve(), Path(agent_comms.__file__).resolve(),
            Path(textual.__file__).resolve(),
        )
        observed = RunObservation(
            frontend, started, time.monotonic_ns(), Path(sys.prefix).resolve(),
            Path.home().resolve(), xdg_config_home().resolve(), xdg_state_home().resolve(),
            xdg_data_home().resolve(), app.tab_order._db.path.resolve(),
            app.colours.wal_directory.resolve(), root,
            opened, storage_rule, saved, acp, regions, history_published, checked,
            agent_ready=bool(acp_states) and all(state.ready for state in acp_states),
            turn_busy=any(state.busy for state in acp_states),
            responses=responses,
            composer_focused=any(editor.has_focus for editor in screen.query(PromptTextArea)),
            composer_regions=tuple(
                CapturedRegion(placement.content_region.intersection(placement.clip))
                for editor in screen.query(PromptTextArea)
                for placement in (published.get(editor),) if placement is not None
            ),
            selected_tabs=tuple(
                entry.identity for entry in sessions.members
                if app.workspace_sessions.source.current(entry.source(sessions))
            ),
        )
        self.target.require_resources(observed)
        self.publish(directory / "result.json", self.observed_result(observed, directory))


@dataclass(frozen=True)
class InstalledOperation(ObserveOperation):
    def observed_result(self, observed: RunObservation, directory: Path) -> PhysicalResult:
        recorded = RuntimeResolution.at(self.target.runtime)
        # This is the installed runtime's stable wire operation, not an import
        # of a concrete probe from a possibly different source-module layout.
        probe = FieldCodec.decode(RuntimeProbe, {
            "kind": "installed_packages", "core": recorded.core_commit,
        })
        packages = FieldCodec.encode(probe.run(), probe.answer_type())
        return InstalledResult(
            observed, Path(sys.executable).resolve(strict=True),
            Path("/proc/self/exe").resolve(strict=True), packages,
        )


@dataclass(frozen=True)
class StopRootOperation(PhysicalOperation):
    """Stop only the private copy, in its own declared runtime; retain its files."""

    target: RunResources

    def execute(self, directory: Path) -> None:
        if LaunchRuntime.running().prefix != self.target.runtime:
            raise ValueError("Private-copy shutdown must run in its declared runtime")
        from agent_comms.comms import wire
        from agent_comms.execution.launch_root import LaunchRoot
        from agent_comms.registry.registry_document import RosterVisibility

        with LaunchRoot.from_path(self.target.root).selected():
            copied = wire()
            for thread in copied.registry.snapshot().visible_threads(RosterVisibility(archived=True)):
                copied.owners.stop(thread.name)
        self.publish(directory / "result.json", StoppedResult(self.target.root))


# Imports, including multiprocessing's __mp_main__, only declare the family.
# Explicit startup/shutdown execution owns its immutable adjacent request.
if __name__ == "__main__":
    PhysicalOperation.execute_file(Path(__file__))
