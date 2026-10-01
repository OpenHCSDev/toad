"""Click a captured native resource in the recorder's isolated st."""

from dataclasses import dataclass
import argparse
import json
import os
from pathlib import Path
import pickle
import re
import subprocess
from abc import abstractmethod

from agent_comms.child_process import ProcessIdentity
from agent_comms.field_codec import FieldCodec
from agent_comms.declared_family import DeclaredFamily
from textual.geometry import Offset, Region


class NativeFocusTarget(DeclaredFamily, affix="Target"):
    """Select a declared native resource, never a guessed pixel coordinate."""

    @classmethod
    @abstractmethod
    def locate(cls, snapshot, args): ...

    @staticmethod
    def selected_view(snapshot):
        return next(view for view in snapshot["views"] if view["mode"] == snapshot["metadata"]["current_mode"])


class HistoryTarget(NativeFocusTarget):
    @classmethod
    def locate(cls, snapshot, args):
        view = cls.selected_view(snapshot)
        resource, = (window for window in view["history_windows"] if window["focus_target"] is not None)
        return resource


class EditorTarget(NativeFocusTarget):
    @classmethod
    def locate(cls, snapshot, args):
        view = cls.selected_view(snapshot)
        resource, = (draft for draft in view["drafts"] if draft["focus_target"] is not None)
        return resource


class ThreadTarget(NativeFocusTarget):
    @classmethod
    def locate(cls, snapshot, args):
        if not args.name:
            raise ValueError("Thread target requires --name")
        return next(row for row in snapshot["metadata"]["navigation_targets"]["threads"] if row["name"] == args.name)


class ChannelTarget(NativeFocusTarget):
    @classmethod
    def locate(cls, snapshot, args):
        if not args.name:
            raise ValueError("Channel target requires --name")
        resource, = (row for row in snapshot["metadata"]["navigation_targets"]["channels"]
                     if row["name"] == args.name)
        return resource


class OriginalTabTarget(NativeFocusTarget):
    @classmethod
    def locate(cls, snapshot, args):
        if args.original_state is None:
            raise ValueError("Original tab requires --original-state")
        original = read_snapshot(args.original_state)
        if original["metadata"]["pid"] != snapshot["metadata"]["pid"]:
            raise ValueError("Original tab snapshot belongs to a different UI")
        mode = original["metadata"]["current_mode"]
        return next(tab for tab in snapshot["metadata"]["navigation_targets"]["tabs"] if tab["name"] == mode)


class PeerTabTarget(NativeFocusTarget):
    """The sole other native tab in a two-session source fixture."""

    @classmethod
    def locate(cls, snapshot, args):
        if args.original_state is None:
            raise ValueError("Peer tab requires --original-state")
        original = read_snapshot(args.original_state)
        if original["metadata"]["pid"] != snapshot["metadata"]["pid"]:
            raise ValueError("Original tab snapshot belongs to a different UI")
        mode = original["metadata"]["current_mode"]
        peer, = (tab for tab in snapshot["metadata"]["navigation_targets"]["tabs"]
                 if tab["name"] != mode)
        return peer


class WidgetTarget(NativeFocusTarget):
    """Click a visible native control by class and optional Textual ID."""

    @classmethod
    def locate(cls, snapshot, args):
        if not args.name:
            raise ValueError("Widget target requires --name Class or Class#id")
        kind, _, identifier = args.name.partition("#")
        focused = snapshot["metadata"]["screen"]["focused"]
        nodes = snapshot["metadata"]["navigation_targets"]["widgets"]
        candidates = [node for node in nodes
                      if node["class"] == kind and (not identifier or node["id"] == identifier)
                      and (not args.focused or (focused is not None
                           and node["object_id"] == focused["object_id"]))]
        if len(candidates) != 1:
            raise ValueError(f"Expected one visible {args.name}, found {len(candidates)}")
        return candidates[0]


def read_snapshot(path):
    output = Path(os.environ["TOAD_VIDEO_OUTPUT"]).resolve()
    state = (path if path.is_absolute() else output / path).resolve()
    if not state.is_relative_to(output):
        raise ValueError("Native target must come from this recorder's owned state")
    return pickle.loads(state.read_bytes())


@dataclass(frozen=True)
class XWindowGeometry:
    width: int
    height: int

    @classmethod
    def read(cls, window_id: str):
        # Decode xdotool's external geometry spelling once at this boundary.
        output = subprocess.check_output(
            ["xdotool", "getwindowgeometry", "--shell", window_id], text=True, timeout=5)
        fields = dict(line.split("=", 1) for line in output.splitlines())
        return cls(int(fields["WIDTH"]), int(fields["HEIGHT"]))


@dataclass(frozen=True)
class StTerminalGrid:
    rows: int
    columns: int
    width: int
    height: int

    def pixel_at(self, cell: Offset, window: XWindowGeometry) -> Offset:
        # st publishes its text-area pixels through TIOCGWINSZ and centers
        # that area inside the actual X11 client (st x.c:cresize).
        if not self.rows or not self.columns or not self.width or not self.height:
            raise ValueError("Native terminal did not publish a pixel grid")
        if self.width % self.columns or self.height % self.rows:
            raise ValueError("Native st pixel grid is not integral")
        cell_width, cell_height = self.width // self.columns, self.height // self.rows
        return Offset((window.width - self.width) // 2 + cell.x * cell_width + cell_width // 2,
                      (window.height - self.height) // 2 + cell.y * cell_height + cell_height // 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path, help="Fresh native recorder state snapshot")
    parser.add_argument("--target", type=NativeFocusTarget.decode, default=HistoryTarget,
                        help="Native resource: " + ", ".join(NativeFocusTarget.names()))
    parser.add_argument("--name", help="Native thread/channel name or widget Class#id")
    parser.add_argument("--focused", action="store_true", help="Select only the currently focused widget")
    parser.add_argument("--original-state", type=Path, help="This run's initial selected-mode snapshot")
    args = parser.parse_args()
    output = Path(os.environ["TOAD_VIDEO_OUTPUT"]).resolve()
    if not output.is_relative_to((Path.home() / ".cache/agent-scratch").resolve()):
        raise ValueError("History click requires owned recorder scratch")
    display_name = os.environ["DISPLAY"]
    if not re.fullmatch(r":[1-9][0-9]*", display_name):
        raise ValueError("History click requires the recorder's isolated display")
    identity = FieldCodec.decode(ProcessIdentity, json.loads(os.environ["TOAD_VIDEO_UI_IDENTITY"]))
    snapshot = read_snapshot(args.state)
    metadata = snapshot["metadata"]
    if metadata["pid"] != identity.pid or not identity.alive():
        raise ValueError("Captured native UI identity changed")
    resource = args.target.locate(snapshot, args)
    target = resource["focus_target"]
    cell = Offset(*target["cell"])
    if cell not in Region(*resource["region"]):
        raise ValueError("Native focus target is outside its resource")
    window_id, = subprocess.check_output(
        ["xdotool", "search", "--pid", os.environ["TOAD_VIDEO_TERMINAL"]], text=True, timeout=5).splitlines()
    client = XWindowGeometry.read(window_id)
    pixel = StTerminalGrid(*metadata["terminal_geometry"]).pixel_at(cell, client)
    observation = {"ui_identity": FieldCodec.encode(identity), "mode": metadata["current_mode"],
                   "resource_object_id": resource["object_id"], "target": target,
                   "terminal_geometry": metadata["terminal_geometry"], "pixel": tuple(pixel)}
    (output / f"{args.target.declared_name}-click-target.json").write_text(json.dumps(observation, indent=2) + "\n")
    subprocess.run(["xdotool", "mousemove", "--sync", "--window", window_id,
                    str(pixel.x), str(pixel.y), "click", "1"], check=True, timeout=5)


if __name__ == "__main__":
    main()
