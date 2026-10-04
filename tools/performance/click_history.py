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
        if args.empty and any(resource["lines"]):
            raise ValueError("Fresh fork submission requires the actual native editor to be empty")
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
        focused = snapshot["metadata"]["screen"]["focused"]
        candidates = [node for node in cls.named_nodes(snapshot, args.name)
                      if (not args.focused or (focused is not None
                           and node["object_id"] == focused["object_id"]))]
        if args.within:
            parent, = cls.named_nodes(snapshot, args.within)
            region = Region(*parent["region"])
            candidates = [node for node in candidates if region.contains_region(Region(*node["region"]))]
        if len(candidates) != 1:
            raise ValueError(f"Expected one visible {args.name}, found {len(candidates)}")
        return candidates[0]

    @staticmethod
    def named_nodes(snapshot, name):
        kind, _, identifier = name.partition("#")
        return [node for node in snapshot["metadata"]["navigation_targets"]["widgets"]
                if node["class"] == kind and (not identifier or node["id"] == identifier)]


class MenuActionTarget(NativeFocusTarget):
    """Select the actual declared action carried by a visible native menu item."""

    @classmethod
    def locate(cls, snapshot, args):
        item, = (node for node in snapshot["metadata"]["navigation_targets"]["widgets"]
                 if node["class"] == "ContextMenuItem" and node.get("action") == args.name)
        return item


class RightSidebarTarget(NativeFocusTarget):
    """The rightmost original sidebar disclosure in this terminal snapshot."""

    @classmethod
    def locate(cls, snapshot, args):
        controls = (node for node in snapshot["metadata"]["navigation_targets"]["widgets"]
                    if node["class"] == "SideBarToggle")
        return max(controls, key=lambda node: node["region"][0])


class ContextTreeTarget(NativeFocusTarget):
    @classmethod
    def reveal(cls, snapshot, args):
        focused = snapshot['metadata']['screen']['focused']
        if (focused['class'], focused['id']) != ('ContextTree', 'context-tree'):
            raise ValueError('Reveal requires the actually focused native context Tree')
        context = cls.selected_view(snapshot)['context']
        node, = (node for node in context['nodes'] if node['key'] == args.name)
        if node['line'] < 0 or context['cursor_line'] < 0:
            raise ValueError('Original member and cursor must be materialized in the native Tree')
        distance = node['line'] - context['cursor_line']
        if distance:
            subprocess.run(['xdotool', 'key', '--repeat', str(abs(distance)),
                            '--repeat-delay', '5', 'Down' if distance > 0 else 'Up'], check=True)

    @classmethod
    def require_selected(cls, snapshot, args):
        context = cls.selected_view(snapshot)['context']
        node, = (node for node in context['nodes'] if node['key'] == args.name)
        if context['selected'] != args.name or node['line'] != context['cursor_line']:
            raise ValueError(f"Original selected reader/cursor differs from {args.name}: "
                             f"{context['selected']} at {context['cursor_line']}; target {node['line']}")

    @classmethod
    def locate(cls, snapshot, args):
        if args.name:
            context = cls.selected_view(snapshot)["context"]
            node, = (node for node in context["nodes"] if node["key"] == args.name)
            if node["target"] is None:
                raise ValueError("Selected original context node has no visible native target")
            return node["target"]
        tree, = (node for node in snapshot["metadata"]["navigation_targets"]["widgets"]
                 if node["class"] == "ContextTree" and node["id"] == "context-tree")
        return tree


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
    parser.add_argument("--button", type=int, choices=(1, 3), default=1)
    parser.add_argument("--within", help="Restrict a widget target to this captured Class#id region")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--drag-columns", type=int, help="Drag from the native target by this many terminal columns")
    action.add_argument("--wheel", type=int, help="Scroll down (positive) or up (negative) over the native target")
    parser.add_argument("--focused", action="store_true", help="Select only the currently focused widget")
    parser.add_argument("--empty", action="store_true", help="Require empty original editor before a fresh fork input")
    parser.add_argument("--original-state", type=Path, help="This run's initial selected-mode snapshot")
    control = parser.add_mutually_exclusive_group()
    control.add_argument('--reveal-context', action='store_true', help='Reveal the materialized original context member with native cursor keys')
    control.add_argument('--require-context-selection', action='store_true', help='Require the original selected context member and native cursor before reader effects')
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
    if args.reveal_context or args.require_context_selection:
        if args.target is not ContextTreeTarget:
            raise ValueError('Context controls require the declared ContextTreeTarget')
        if args.reveal_context:
            ContextTreeTarget.reveal(snapshot, args)
        else:
            ContextTreeTarget.require_selected(snapshot, args)
        return
    resource = args.target.locate(snapshot, args)
    target = resource["focus_target"]
    cell = Offset(*target["cell"])
    if cell not in Region(*resource["region"]):
        raise ValueError("Native focus target is outside its resource")
    window_id, = subprocess.check_output(
        ["xdotool", "search", "--pid", os.environ["TOAD_VIDEO_TERMINAL"]], text=True, timeout=5).splitlines()
    client = XWindowGeometry.read(window_id)
    grid = StTerminalGrid(*metadata["terminal_geometry"])
    pixel = grid.pixel_at(cell, client)
    gesture = []
    if args.drag_columns is not None:
        destination = cell + Offset(args.drag_columns, 0)
        if destination not in Region(0, 0, grid.columns, grid.rows):
            raise ValueError("Native drag destination lies outside the owned terminal")
        end = grid.pixel_at(destination, client)
        gesture = ["mousedown", "1", "mousemove", "--sync", "--window", window_id,
                   str(end.x), str(end.y), "mouseup", "1"]
    elif args.wheel is not None:
        if not args.wheel:
            raise ValueError("A native wheel gesture requires nonzero movement")
        gesture = ["click", "--repeat", str(abs(args.wheel)), "4" if args.wheel < 0 else "5"]
    else:
        gesture = ["click", str(args.button)]
    observation = {"ui_identity": FieldCodec.encode(identity), "mode": metadata["current_mode"],
                   "resource_object_id": resource["object_id"], "target": target, "button": args.button,
                   "terminal_geometry": metadata["terminal_geometry"], "pixel": tuple(pixel),
                   "gesture": gesture}
    (output / f"{args.target.declared_name}-click-target.json").write_text(json.dumps(observation, indent=2) + "\n")
    subprocess.run(["xdotool", "mousemove", "--sync", "--window", window_id,
                    str(pixel.x), str(pixel.y), *gesture], check=True, timeout=5)


if __name__ == "__main__":
    main()
