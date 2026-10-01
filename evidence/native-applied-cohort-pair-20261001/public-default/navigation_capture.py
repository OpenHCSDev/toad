"""Read-only ordinary default navigation through the existing physical recorder."""
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests/tools"))
sys.path.insert(0, str(ROOT / "tools/performance"))
import record_installed_tui as recorder
import click_history as click
from textual.geometry import Region

class VisibleChannelTarget(click.NativeFocusTarget):
    @classmethod
    def locate(cls, snapshot, args):
        candidates = []
        for node in snapshot["metadata"]["compositor"]["maps"]["full"]["nodes"]:
            if node["class"] != "CommsRow":
                continue
            geometry = node["geometry"]
            region = Region(*geometry["region"]).intersection(Region(*geometry["clip"]))
            if region.width and region.height:
                candidates.append({**node, "region": tuple(region),
                    "focus_target": {"widget": node,
                                     "cell": tuple(int(value) for value in region.center)}})
        return min(candidates, key=lambda node: node["region"][1])

class DefaultNavigationJourney(recorder.PhysicalJourney):
    @classmethod
    def script(cls, args):
        if not args.capture_state or args.peer_thread != "openhcs-pr159-viewer-bind-owner":
            raise ValueError("Readonly navigation requires native state and the reviewed retained peer")
        channel = "exec --sync " + shlex.join([
            sys.executable, str(Path(__file__).resolve()), "--click",
            "--target", "visible_channel", "--state", "before-state.pickle"])
        marker = recorder.marker_command()
        def mark(label, thread=None):
            return marker + label + (" --wait-history-seconds 10 --wait-history-thread " + thread if thread else "")
        return "\n".join([
            channel, "sleep 2", mark("channel-open"),
            recorder.native_click_command("phase-channel-open-state.pickle", target="thread", name=args.peer_thread),
            "sleep 3", mark("peer-open", args.peer_thread),
            recorder.native_click_command("phase-peer-open-state.pickle", target="original_tab", original_state="before-state.pickle"),
            "sleep 1", mark("return-a", "nra-architecture"),
            recorder.native_click_command("phase-return-a-state.pickle", target="original_tab", original_state="phase-peer-open-state.pickle"),
            "sleep 1", mark("return-b", args.peer_thread),
            recorder.native_click_command("phase-return-b-state.pickle", target="original_tab", original_state="before-state.pickle"),
            "sleep 1", mark("final-a", "nra-architecture"),
        ]) + "\n"

if __name__ == "__main__":
    if sys.argv[1:2] == ["--click"]:
        del sys.argv[1]
        click.main()
    else:
        recorder.main()
