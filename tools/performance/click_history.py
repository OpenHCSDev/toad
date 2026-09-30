"""Click a captured native history gutter or editor in the recorder's isolated st."""

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
    def locate(cls, view): ...


class HistoryTarget(NativeFocusTarget):
    @classmethod
    def locate(cls, view):
        resource, = (window for window in view["history_windows"] if window["focus_target"] is not None)
        return resource


class EditorTarget(NativeFocusTarget):
    @classmethod
    def locate(cls, view):
        resource, = (draft for draft in view["drafts"] if draft["focus_target"] is not None)
        return resource


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
    args = parser.parse_args()
    output = Path(os.environ["TOAD_VIDEO_OUTPUT"]).resolve()
    if not output.is_relative_to((Path.home() / ".cache/agent-scratch").resolve()):
        raise ValueError("History click requires owned recorder scratch")
    display_name = os.environ["DISPLAY"]
    if not re.fullmatch(r":[1-9][0-9]*", display_name):
        raise ValueError("History click requires the recorder's isolated display")
    identity = FieldCodec.decode(ProcessIdentity, json.loads(os.environ["TOAD_VIDEO_UI_IDENTITY"]))
    state = (args.state if args.state.is_absolute() else output / args.state).resolve()
    if not state.is_relative_to(output):
        raise ValueError("History target must come from this recorder's owned state")
    snapshot = pickle.loads(state.read_bytes())
    metadata = snapshot["metadata"]
    if metadata["pid"] != identity.pid or not identity.alive():
        raise ValueError("Captured native UI identity changed")
    view = next(view for view in snapshot["views"] if view["mode"] == metadata["current_mode"])
    resource = args.target.locate(view)
    target = resource["focus_target"]
    cell = Offset(*target["cell"])
    if cell not in Region(*resource["region"]):
        raise ValueError("Native focus target is outside its resource")
    window_id, = subprocess.check_output(
        ["xdotool", "search", "--pid", os.environ["TOAD_VIDEO_TERMINAL"]], text=True, timeout=5).splitlines()
    client = XWindowGeometry.read(window_id)
    pixel = StTerminalGrid(*metadata["terminal_geometry"]).pixel_at(cell, client)
    observation = {"ui_identity": FieldCodec.encode(identity), "mode": view["mode"],
                   "resource_object_id": resource["object_id"], "target": target,
                   "terminal_geometry": metadata["terminal_geometry"], "pixel": tuple(pixel)}
    (output / f"{args.target.declared_name}-click-target.json").write_text(json.dumps(observation, indent=2) + "\n")
    subprocess.run(["xdotool", "mousemove", "--sync", "--window", window_id,
                    str(pixel.x), str(pixel.y), "click", "1"], check=True, timeout=5)


if __name__ == "__main__":
    main()
