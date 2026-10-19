"""Capture real sidebar paint on a private wire and physical st/Xvfb display.

Uses the installed Core and terminal dependencies; PYTHONPATH selects Toad source.
The controller is a real external participant, publishing its own working/idle
activity and real wire messages. No provider requests or synthetic widgets.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


def frontend(output: Path, project: str) -> None:
    from toad.widgets.comms_sidebar import CommsRow
    from ui_theme.effects import NEW_MESSAGE, NEW_TEXT, SIDEBAR_ENTER
    from ui_theme.scheme import AccentColour

    trace = (output / "paint.jsonl").open("w", buffering=1)
    render = CommsRow.render_line

    def recorded(row, y, paint):
        strip = render(row, y, paint)
        if y == 0:
            layer = row.paint_layer
            trace.write(json.dumps(dict(
                at=time.monotonic(), target=row.target_name,
                widget=type(row).__name__, opacity=row.paint_opacity,
                layer_opacity=layer.layer_opacity, inherited_opacity=paint.opacity,
                foreground=str(paint.foreground), background=str(paint.background),
                accent=str(row.app.colours.colour(AccentColour)),
                effects={name: dict(amount=getattr(row.effect_frame(effect), "amount", None),
                                    elapsed=row.effects[effect].elapsed)
                         for name, effect in (("message", NEW_MESSAGE), ("text", NEW_TEXT),
                                              ("enter", SIDEBAR_ENTER)) if effect in row.effects},
                runs=[dict(text=segment.text, style=str(segment.style)) for segment in strip],
            )) + "\n")
        return strip

    CommsRow.render_line = recorded
    from toad.cli import main
    sys.argv = ["toad", "acp", f"{sys.executable} -m agent_comms.acp", project,
                "--title", "Row flash capture", "--session", "flash-observer"]
    main()


def capture(output: Path) -> None:
    from build_runtime import BuildDisplay, TerminalApp

    output.mkdir(parents=True)
    home = output / "home"
    home.mkdir()
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("AGENT_COMMS_", "PI_", "XDG_"))
                   and key not in ("NO_COLOR", "TOAD_VALIDATION")}
    environment.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "config"),
                       XDG_STATE_HOME=str(home / "state"), XDG_DATA_HOME=str(home / "data"),
                       AGENT_COMMS_ROOT=str(output / "wire"))
    cli = [sys.executable, "-m", "agent_comms.cli", "--root", str(output / "wire")]
    def core(*args):
        return json.loads(subprocess.check_output([*cli, *args], env=environment, text=True))
    project = str(Path.cwd())
    core("register", "--name", "flash-observer", "--worktree", project, "--tags", "flash")
    core("register", "--name", "flash-peer", "--worktree", project, "--tags", "flash",
         "--execution", "external", "--pid", str(os.getpid()))
    events = []
    def event(label, *args):
        submitted = time.monotonic()
        result = core(*args)
        events.append(dict(submitted=submitted, at=time.monotonic(), label=label, result=result))
        (output / "events.json").write_text(json.dumps(events, indent=2))
    command = [sys.executable, str(Path(__file__).resolve()), "--frontend", str(output), project]
    with BuildDisplay(output) as display, TerminalApp(command, display, output / "terminal", environment, home) as app:
        app.wait("ready", lambda text: "flash-observer" in text and "Session details" in text, seconds=45)
        # Open the left sidebar through its real key binding, then move off it.
        app.keys("ctrl+b")
        app.wait("sidebar", lambda text: "flash-peer" in text)
        app.click_cell(app.columns // 2, app.rows - 4)
        time.sleep(1)
        event("dm", "send", "--from", "flash-peer", "--to", "user", "--body", "Row flash: direct message")
        time.sleep(1)
        event("working", "activity", "--name", "flash-peer", "--state", "working", "--detail", "Capturing row flash")
        time.sleep(1)
        app.screenshot("working-settled")
        event("channel", "send", "--from", "flash-peer", "--to", "#flash", "--body", "Row flash: channel message")
        time.sleep(1)
        event("idle", "activity", "--name", "flash-peer", "--state", "idle")
        time.sleep(1)
        app.screenshot("idle-settled")
        (output / "screen.txt").write_text(app.capture())


if __name__ == "__main__":
    if sys.argv[1] == "--frontend":
        frontend(Path(sys.argv[2]), sys.argv[3])
    else:
        capture(Path(sys.argv[1]).resolve())
