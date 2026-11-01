"""One physical Toad run: private source/home, owned Xvfb/st, observed input.

Acceptance and performance use these same existing display/terminal types.
The installed source runtime creates history; only that copy is rebound to a
candidate. A closed run retains its files, including failed/UNKNOWN evidence.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, ExitStack, contextmanager
import ctypes
from dataclasses import dataclass
import itertools
import os
from pathlib import Path
import re
import select
import socket
import struct
import subprocess
import sys
import time
from typing import get_args, get_type_hints

from agent_comms.active_route import ActiveRoute, active_route_path, route_new_bus
from agent_comms.bus import Bus
from agent_comms.check_root import CheckRoot
from agent_comms.child_process import DetachedChildStdio, ProcessIdentity, SpawnedProcess
from agent_comms.comms import Comms
from agent_comms.installer.practice import SuppliedRuntimeHome
from agent_comms.installer.runtime_resolution import RuntimeResolution
from agent_comms.launch_root import LaunchRoot
from agent_comms.launch_runtime import LaunchRuntime, ThreadLaunch
from agent_comms.nominal.field_codec import FieldCodec
from agent_comms.recorded_bus import RecordedBusIdentity
from agent_comms.root_runtime import RootRuntime
from agent_comms.store_files import ExclusiveAtomicFile
from rich.cells import cell_len
from rich.segment import Segment
from textual.geometry import Region, Size
from textual.strip import Strip
from ui_theme.wal import WalFile

from physical_ui_remote import (
    AdmitOperation, CapturedRegion, ExecOperation, ObserveOperation, PendingRun, PhysicalOperation,
    ProcessRetirement, RunObservation, RunTarget, StopRootOperation,
)


class XvfbDisplay(AbstractContextManager):
    """Own a connection to a local framebuffer, resolving aliases at Xlib.

    This resource has no raw-input entrypoint. Only TerminalApp may drive its
    window after checking the actual application/source on that incarnation.
    """

    def __init__(self, name: str):
        if not name:
            raise ValueError("An explicit isolated Xvfb display is required")
        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XConnectionNumber.argtypes = [ctypes.c_void_p]
        x11.XConnectionNumber.restype = ctypes.c_int
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.restype = ctypes.c_int
        x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
        x11.XDefaultScreen.restype = ctypes.c_int
        x11.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XDisplayWidth.restype = ctypes.c_int
        x11.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XDisplayHeight.restype = ctypes.c_int
        connection = x11.XOpenDisplay(name.encode())
        if not connection:
            raise ValueError(f"Cannot connect to isolated Xvfb display: {name}")
        with ExitStack() as close_display:
            close_display.callback(x11.XCloseDisplay, connection)
            with socket.fromfd(x11.XConnectionNumber(connection), socket.AF_UNIX, socket.SOCK_STREAM) as peer:
                pid, uid, _gid = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                address = Path(os.fsdecode(peer.getpeername()).lstrip("\0"))
            process = ProcessIdentity.capture(pid)
            if address.name == "X0" or uid != os.getuid() or Path(f"/proc/{pid}/exe").resolve().name != "Xvfb":
                raise ValueError(f"Not an owned isolated Xvfb resource: {name}")
            self.name, self.process = name, process
            self.x11, self.connection = x11, connection
            self.close_display = close_display.pop_all()

    @property
    def environment(self) -> dict[str, str]:
        return {**os.environ, "DISPLAY": self.name}

    @property
    def size(self) -> Size:
        screen = self.x11.XDefaultScreen(self.connection)
        return Size(self.x11.XDisplayWidth(self.connection, screen),
                    self.x11.XDisplayHeight(self.connection, screen))

    @contextmanager
    def recording(self, path: Path, environment: Mapping[str, str]):
        """Record this display from startup through frontend retirement."""
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        size = self.size
        with path.with_suffix(".log").open("wb") as log:
            with SpawnedProcess.launch(
                ("ffmpeg", "-hide_banner", "-loglevel", "warning", "-n", "-f", "x11grab",
                 "-framerate", "25", "-video_size", f"{size.width}x{size.height}",
                 "-i", self.name, "-c:v", "libx264", "-preset", "ultrafast",
                 "-pix_fmt", "yuv420p", str(path)),
                env=environment,
                stdio=DetachedChildStdio(stdin=subprocess.PIPE, stdout=log, stderr=log),
            ) as child:
                PhysicalOperation.publish(path.with_suffix(".process.json"), child.identity)
                try:
                    yield path
                finally:
                    try:
                        child.process.communicate(b"q", timeout=10)
                        if child.process.returncode:
                            raise RuntimeError(f"Physical recording failed; see {log.name}")
                    finally:
                        outcome = child.stop_sync(deadline=time.monotonic() + 10)
                        PhysicalOperation.publish(path.with_suffix(".retired.json"),
                                                  ProcessRetirement(child.identity, outcome))

    def __exit__(self, *exception):
        return self.close_display.__exit__(*exception)


class OwnedDisplay(XvfbDisplay):
    """The isolated display this run creates and retires."""

    startup_seconds = 10.0
    stop_seconds = 10.0
    default_size = Size(1600, 1000)

    def __init__(self, output: Path, *, size: Size = default_size):
        self.output = output
        output.mkdir(parents=True, exist_ok=True)
        self.log = (output / "xvfb.log").open("wb")
        self.server = SpawnedProcess.launch(
            ("Xvfb", "-displayfd", "1", "-screen", "0", f"{size.width}x{size.height}x24", "-nolisten", "tcp"),
            stdio=DetachedChildStdio(stdout=subprocess.PIPE, stderr=self.log),
        )
        try:
            stream = self.server.process.stdout
            ready, _, _ = select.select((stream,), (), (), self.startup_seconds)
            if not ready:
                raise TimeoutError("Xvfb did not publish its allocated display")
            name = ":" + stream.readline().decode().strip()
            super().__init__(name)
            if self.process != self.server.identity:
                self.close_display.close()
                raise ValueError("Xlib connected to a server this run did not create")
            PhysicalOperation.publish(output / "xvfb-process.json", self.process)
        except BaseException:
            self.close_server()
            raise

    def close_server(self) -> None:
        try:
            outcome = self.server.stop_sync(deadline=time.monotonic() + self.stop_seconds)
            PhysicalOperation.publish(self.output / "xvfb-retired.json",
                                      ProcessRetirement(self.server.identity, outcome))
        finally:
            self.server.close_streams()
            self.log.close()

    def __exit__(self, *exception):
        try:
            return super().__exit__(*exception)
        finally:
            self.close_server()


@dataclass(frozen=True)
class ScreenCapture:
    """Real st text paired with the published viewport geometry observed for it."""

    text: str
    history_regions: tuple[CapturedRegion, ...]

    def message_rows(self):
        lines = self.text.splitlines()
        for captured in self.history_regions:
            region = captured.region
            for row in range(max(0, region.y), min(len(lines), region.bottom)):
                yield row, Strip([Segment(lines[row])]).crop(region.x, region.right).text

    def messages(self):
        message = None
        for _, cell in self.message_rows():
            body = cell.rstrip()
            content = body.lstrip("▌").strip()
            if not body.startswith("▌") or content.startswith(("─", "▶")):
                if message:
                    yield message
                message = "" if content.startswith("─") else None
            elif message is not None:
                message += "".join(content.split())
        if message:
            yield message

    def reader_position(self):
        for row, cell in self.message_rows():
            if cell.startswith("▌") and cell.strip("▌ "):
                return row, cell
        return ()


class TerminalApp:
    """Own one isolated st window, actual-source checks and all physical input."""

    startup_seconds = 60.0
    stop_seconds = 10.0
    # One source snapshot belongs to the controller's Python module lifetime,
    # not to each callback executing inside a foreign running application.
    with Path(__file__).with_name("physical_ui_remote.py").open("rb") as _source:
        operation_program = _source.read(PhysicalOperation.source_bytes + 1)
    if len(operation_program) > PhysicalOperation.source_bytes:
        raise ValueError("Physical operation source exceeds its bound")

    def __init__(self, command: tuple[str, ...], display: XvfbDisplay, output: Path,
                 target: RunTarget, cwd: Path, *, size: Size = Size(140, 40)):
        self.command, self.display, self.output = tuple(map(str, command)), display, output
        self.target, self.cwd, self.requested_size = target, cwd, size
        environment = LaunchRoot.environment(ThreadLaunch.strip(dict(os.environ)))
        for key in tuple(environment):
            if key.startswith("XDG_") or key in ("PYTHONPATH", "PYTHONHOME", "NO_COLOR", "TOAD_VALIDATION"):
                del environment[key]
        environment.update(
            HOME=str(target.home), DISPLAY=display.name,
            XDG_CONFIG_HOME=str(target.config), XDG_STATE_HOME=str(target.state),
            XDG_DATA_HOME=str(target.data),
            PYWAL_CACHE_DIR=str(target.palette),
            AGENT_COMMS_RUNTIME_ROOT=str(target.launch_runtime.interpreter.parent),
        )
        self.environment = environment
        self.operations = itertools.count()

    @property
    def columns(self) -> int:
        return self.grid_size.width

    @property
    def rows(self) -> int:
        return self.grid_size.height

    @staticmethod
    def prepare_target(root: Path, runtime: LaunchRuntime) -> RunTarget:
        """Prepare a fresh frontend home beside an already owned private root.

        Only presentation settings travel. Saved Toad databases/tabs never do.
        Existing installer acceptance and copied-history runs share this setup.
        """
        from toad.preferences import INTERFACE, SETTINGS, SavedSettings, ToadSettings

        root = root.resolve(strict=True)
        build = RuntimeResolution.at(runtime.prefix)
        build.interpreter.require_recorded()
        home = root.parent / "frontend-home"
        # Validate the intended paths before touching the home. RunTarget also
        # rejects the real user's home/workspace and an unrelated bus.
        if home.exists():
            raise FileExistsError(f"A physical run needs fresh frontend persistence: {home}")
        # The source root has already been created by CheckRoot/the installer.
        # Its parent is the run workspace, never the user's real home.
        import pwd
        user_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        if root.parent == user_home or user_home.is_relative_to(root.parent):
            raise ValueError("Refusing frontend setup beside a live user root")
        home.mkdir(mode=0o700)
        SuppliedRuntimeHome(home, runtime).prepare()
        target = RunTarget(root, home.resolve(), runtime.prefix, build)
        for directory in (target.config, target.state, target.data):
            directory.mkdir(mode=0o700)
        settings = SavedSettings.path()
        destination = target.config / settings.parent.name / settings.name
        destination.parent.mkdir(mode=0o700)
        selected = {}
        if settings.is_file():
            raw = FieldCodec.decode(dict[str, object], FieldCodec.parse(settings.read_text()))
            annotations = get_type_hints(ToadSettings, include_extras=True)
            presentation = frozenset(key for field, key in FieldCodec.record_fields(ToadSettings)
                                     if INTERFACE in get_args(annotations[field.name]))
            selected = {key: value for key, value in raw.items() if key in presentation}
        private_settings = SavedSettings(selected)
        private_settings.set(SETTINGS.statistics.allow_collect, False)
        ExclusiveAtomicFile(destination).write_bytes(private_settings.json.encode())
        palette = WalFile.directory(os.environ) / WalFile.NAME
        if palette.is_file():
            target.palette.mkdir(mode=0o700, parents=True)
            destination = target.palette / WalFile.NAME
            ExclusiveAtomicFile(destination).write_bytes(palette.read_bytes())
            WalFile.read(destination)  # Validate the exact copied bytes through their format owner.
        route = ActiveRoute(root, RecordedBusIdentity.capture(Bus.path_in(root)))
        route_path = home / active_route_path().relative_to(Path.home())
        route_new_bus(route, route_path)
        return target

    @classmethod
    @contextmanager
    def copied(cls, source: Comms, threads: tuple[str, ...], runtime: LaunchRuntime,
               output: Path, *, thread: str, size: Size = Size(140, 40),
               framebuffer: Size = OwnedDisplay.default_size) -> Iterator[TerminalApp]:
        """Create under the source owner, bind only its copy, retain run evidence."""
        output = output.expanduser().absolute()
        output.mkdir(mode=0o700, parents=True)  # Fresh evidence, never overwrite a failed run.
        copied = CheckRoot(source, threads, output / "bus").create()
        RootRuntime.publish(copied.root, runtime)
        target = cls.prepare_target(copied.root, runtime)
        try:
            with OwnedDisplay(output / "display", size=framebuffer) as display:
                # Keep the real default launcher: its root/runtime succession is
                # precisely what the post-attachment observation must establish.
                command = (str(Path.home() / ".local/bin/toad-comms"), thread)
                app = cls(command, display, output / "frontend", target, target.home, size=size)
                with display.recording(output / "journey.mp4", app.environment), app:
                    yield app
        finally:
            # Shutdown uses the copy's own runtime, not a foreign source Comms.
            # Files remain until the actual acceptance and borrower checks retire them.
            cls.stop_copy(target, output / "retirement")

    @classmethod
    def operation_file(cls, operation: PhysicalOperation, directory: Path) -> Path:
        directory.mkdir(mode=0o700, parents=True)
        # The declaration module owns one bounded program snapshot for this
        # controller lifetime. Later source edits cannot change a run's wire.
        raw = cls.operation_program
        script = directory / "operation.py"
        # remote_exec supplies no module filename. Bind only that external
        # datum; the program stays in its reviewed source file and the request
        # stays in FieldCodec's adjacent record, as in capture_history.
        filename = f"__file__ = {str(script)!r}\n".encode()
        ExclusiveAtomicFile(script).write_bytes(filename + raw)
        PhysicalOperation.publish(script.with_suffix(".json"), operation)
        return script

    @staticmethod
    def result(directory: Path):
        error = directory / "error.json"
        path = error if error.exists() else directory / "result.json"
        return PhysicalOperation.read_result(path).require()

    @classmethod
    def stop_copy(cls, target: RunTarget, directory: Path) -> None:
        script = cls.operation_file(StopRootOperation(target), directory)
        with SpawnedProcess.launch(
            (str(target.launch_runtime.interpreter), "-I", str(script)),
            env=LaunchRoot.environment(ThreadLaunch.strip(dict(os.environ))),
        ) as child:
            child.collect(timeout=30).check_returncode()
        cls.result(directory)

    def _packet(self, operation: PhysicalOperation) -> Path:
        return self.operation_file(operation, self.output / "operations" / f"{next(self.operations):06d}")

    def __enter__(self):
        self.output.mkdir(mode=0o700, parents=True)
        self.dump = self.output / "st-screen.txt"
        self.log = (self.output / "st.log").open("wb")
        script = self._packet(ExecOperation(self.target, ProcessIdentity.current(), self.command))
        self.terminal = SpawnedProcess.launch(
            ("st", "-f", "DejaVu Sans Mono:pixelsize=16",
             "-g", f"{self.requested_size.width}x{self.requested_size.height}", "-o", str(self.dump), "-e", "env",
             f"HOME={self.target.home}", f"XDG_CONFIG_HOME={self.target.config}",
             f"XDG_STATE_HOME={self.target.state}", f"XDG_DATA_HOME={self.target.data}",
             str(self.target.launch_runtime.interpreter), "-I", str(script)),
            cwd=self.cwd, env=self.environment,
            stdio=DetachedChildStdio(stdout=self.log, stderr=self.log),
        )
        try:
            PhysicalOperation.publish(self.output / "st-process.json", self.terminal.identity)
            self.window = int(subprocess.check_output(
                ("xdotool", "search", "--sync", "--onlyvisible", "--pid", str(self.terminal.identity.pid)),
                env=self.environment, text=True, timeout=10).splitlines()[0])
            deadline = time.monotonic() + self.startup_seconds
            self._await_result(script.parent, deadline)
            self.frontend = self.result(script.parent).process()
            # Wait until the exec wrapper has left and the real interpreter has
            # emitted terminal data. Neither is application/source readiness:
            # that answer comes from the live Toad owner in observe() below.
            while (Path(f"/proc/{self.frontend.pid}/exe").resolve()
                   != self.target.launch_runtime.interpreter.resolve()
                   or os.fsencode(script) in Path(f"/proc/{self.frontend.pid}/cmdline").read_bytes()
                   or not self.dump.stat().st_size):
                self._require_starting(deadline)
                time.sleep(.05)
            self.read_grid()
            while True:
                try:
                    self.admission = self._observe(AdmitOperation).admitted(self.target)
                    PhysicalOperation.publish(self.output / "build-admitted.json", self.admission)
                    break
                except PendingRun:
                    self._require_starting(deadline)
                    time.sleep(.1)
            # -o enables st's raw printer too. Even these printer keys pass the
            # same source admission as every later physical key/click.
            self.keys("ctrl+Print")
            self.wait("terminal", lambda screen: bool(screen.text.strip()))
            return self
        except BaseException:
            self.close()
            raise

    def _require_starting(self, deadline: float) -> None:
        if self.terminal.process.poll() is not None or time.monotonic() >= deadline:
            raise TimeoutError(f"Physical frontend did not become ready; see {self.output}")

    def _await_result(self, directory: Path, deadline: float) -> None:
        while not ((directory / "result.json").exists() or (directory / "error.json").exists()):
            self._require_starting(deadline)
            time.sleep(.02)

    def _observe(self, operation: type[ObserveOperation]):
        self.terminal.platform.require(self.frontend)
        script = self._packet(operation(self.target, self.frontend, Path(__file__).resolve().parent))
        # This controller is an ancestor of its st/frontend. No arbitrary PID,
        # helper privilege escalation, installed-file edit or source retry.
        sys.remote_exec(self.frontend.pid, str(script))
        self._await_result(script.parent, time.monotonic() + PhysicalOperation.timeout)
        result = self.result(script.parent)
        if result.observation().frontend.process != self.frontend:
            raise ValueError("Observation belongs to another frontend incarnation")
        self.terminal.platform.require(self.terminal.identity)
        self.server_identity()
        owner = subprocess.check_output(
            ("xprop", "-display", self.display.name, "-id", str(self.window), "_NET_WM_PID"),
            env=self.environment, text=True, timeout=5,
        )
        if int(owner.partition("=")[2].strip()) != self.terminal.identity.pid:
            raise ValueError("Window does not belong to this run's st frontend")
        self.read_grid()
        return result

    def observe(self) -> RunObservation:
        current = self._observe(ObserveOperation).observation()
        return self.admission.observe(self.target, current)

    def input(self, *commands: str) -> RunObservation:
        observed = self.observe()
        PhysicalOperation.publish(
            self.output / "operations" / f"input-{next(self.operations):06d}.json", observed,
        )
        subprocess.run(
            ("xdotool", "windowfocus", "--sync", str(self.window), *commands),
            env=self.environment, check=True, timeout=10,
        )
        return observed

    def server_identity(self) -> None:
        with XvfbDisplay(self.display.name) as actual:
            if actual.process != self.display.process:
                raise ValueError("The run's Xvfb incarnation changed")

    def keys(self, *keys: str) -> RunObservation:
        return self.input("key", "--clearmodifiers", *keys)

    def type_text(self, text: str) -> None:
        self.input("type", "--clearmodifiers", "--delay", "1", text)

    def capture(self):
        """Read st's own print-screen output; screenshots record the visible window."""
        offset = self.dump.stat().st_size
        observed = self.keys("shift+Print")
        deadline = time.monotonic() + 2
        while True:
            with self.dump.open("rb") as stream:
                stream.seek(offset)
                data = stream.read()
            if data.count(b"\n") >= self.rows:
                return ScreenCapture(data.decode("utf-8"), observed.history_regions)
            if self.terminal.process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("st did not finish its screen dump")
            time.sleep(.02)

    def reader_place(self, name):
        previous = ()

        def settled(screen):
            nonlocal previous
            rows = screen.reader_position()
            same = "Agent Comms connected" not in screen.text and bool(rows) and rows == previous
            previous = rows
            return same

        return self.wait(name, settled).reader_position()

    def screenshot(self, name):
        self.observe()
        path = self.output / f"{name}.png"
        subprocess.run(("import", "-display", self.display.name, "-window", str(self.window), str(path)),
                       check=True, timeout=10)
        return path

    def wait(self, name, predicate, seconds=60):
        deadline = time.monotonic() + seconds
        previous = ""
        changes = self.output / f"{name}-changes.txt"
        while True:
            screen = self.capture()
            text = screen.text
            if text != previous:
                with changes.open("a") as log:
                    log.write(f"\n--- {time.monotonic()} ---\n{text}")
                previous = text
            if predicate(screen):
                (self.output / f"{name}.txt").write_text(text)
                return screen
            if self.terminal.process.poll() is not None or time.monotonic() >= deadline:
                (self.output / f"{name}-failed.txt").write_text(text)
                self.screenshot(f"{name}-failed")
                raise RuntimeError(f"Terminal probe {name} failed; see {self.output}")
            time.sleep(.2)

    def show_thread(self, thread):
        self.wait("ready", lambda screen: thread in screen.text
                  and "▶ Ready" in "\n".join(screen.text.splitlines()[-8:]))
        self.click_cell(self.columns - 1, self.rows // 2)
        return self.wait("shown", lambda screen: "User messages" in screen.text and all(
            "Indexing" not in line.split("│", 1)[0] for line in screen.text.splitlines()))

    def click(self, label):
        text = self.wait("find-" + label.replace("/", "-"), lambda screen: any(
            label in line.split("│", 1)[0] for line in screen.text.splitlines())).text
        row, line = next((row, line) for row, line in enumerate(text.splitlines())
                         if label in line.split("│", 1)[0])
        self.click_cell(cell_len(line[:line.index(label)]) + cell_len(label) // 2, row)

    def toggle_group(self, label):
        def header(line):
            return line.split("│", 1)[0].lstrip().startswith(("▾ " + label, "▸ " + label))
        text = self.wait("find-group-" + label, lambda screen: any(map(header, screen.text.splitlines()))).text
        row, line = next((row, line) for row, line in enumerate(text.splitlines()) if header(line))
        glyph = min(index for index in (line.find("▾"), line.find("▸")) if index >= 0)
        self.click_cell(cell_len(line[:glyph]), row)

    def hide_category(self, label):
        def control(text):
            return next(((row, line) for row, line in enumerate(text.splitlines())
                         if "│" in line and label in line.rsplit("│", 1)[-1]), None)
        text = self.wait("find-filter-" + label.replace("/", "-"), lambda screen: control(screen.text) is not None).text
        row, line = control(text)
        prefix, panel = line.rsplit("│", 1)
        self.click_cell(cell_len(prefix + "│" + panel[:panel.index("▐")]) + 1, row)

    def read_grid(self):
        """Derive cells/padding from st's own X size hints, including after resize."""
        geometry = subprocess.check_output(
            ("xdotool", "getwindowgeometry", "--shell", str(self.window)),
            env=self.environment, text=True, timeout=5)
        size = dict(line.split("=", 1) for line in geometry.splitlines() if "=" in line)
        hints = subprocess.check_output(
            ("xprop", "-display", self.display.name, "-id", str(self.window), "WM_NORMAL_HINTS"),
            env=self.environment, text=True, timeout=5)
        declared = {name: (int(width), int(height)) for name, width, height in re.findall(
            r"program specified (minimum size|base size): (\d+) by (\d+)", hints)}
        base_x, base_y = declared["base size"]
        minimum_x, minimum_y = declared["minimum size"]
        self.cell_width, self.cell_height = minimum_x - base_x, minimum_y - base_y
        self.border_x, self.border_y = base_x / 2, base_y / 2
        self.window_region = Region(int(size["X"]), int(size["Y"]), int(size["WIDTH"]), int(size["HEIGHT"]))
        self.require_visible(self.window_region)
        self.grid_size = Size((self.window_region.width - base_x) // self.cell_width,
                              (self.window_region.height - base_y) // self.cell_height)

    def require_visible(self, region: Region) -> None:
        if not Region(0, 0, *self.display.size).contains_region(region):
            raise ValueError(f"Terminal {region} exceeds the owned framebuffer {self.display.size}")

    def click_cell(self, column, row):
        self.read_grid()
        x = int(self.border_x + (column + .5) * self.cell_width)
        y = int(self.border_y + (row + .5) * self.cell_height)
        self.input("mousemove", "--window", str(self.window), str(x), str(y), "click", "1")

    def resize(self, columns: int, rows: int) -> None:
        self.read_grid()
        width = int(2 * self.border_x + columns * self.cell_width)
        height = int(2 * self.border_y + rows * self.cell_height)
        self.require_visible(Region(self.window_region.x, self.window_region.y, width, height))
        self.input("windowsize", "--sync", str(self.window), str(width), str(height))
        self.read_grid()

    def close(self) -> None:
        """Retire one child lifetime on normal exit and failed entry alike."""
        try:
            outcome = self.terminal.stop_sync(deadline=time.monotonic() + self.stop_seconds)
            PhysicalOperation.publish(self.output / "st-retired.json",
                                      ProcessRetirement(self.terminal.identity, outcome))
        finally:
            self.terminal.close_streams()
            self.log.close()

    def __exit__(self, exception_type, exception, traceback):
        try:
            # An exceptional/uncertain operation is not permission for another
            # attachment or input. Retire only the already owned child instead.
            if exception_type is None and self.terminal.process.poll() is None:
                final = self._observe(AdmitOperation).admitted(self.target)
                self.admission.observe(self.target, final.observation())
                if final.build != self.admission.build:
                    raise ValueError("The verified runtime build changed during the physical run")
                PhysicalOperation.publish(self.output / "build-final.json", final)
                self.keys("ctrl+q")
                self.terminal.process.wait(timeout=5)
        finally:
            self.close()
