"""Capture actual st pixels on private Xvfb; requires st, xdotool, Pillow, python-xlib."""

import json
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from PIL import ImageGrab
from Xlib.display import Display


def main():
    terminal_bin = shutil.which("st")
    if terminal_bin is None:
        raise RuntimeError("This visual check requires the real st terminal")
    root = Path(tempfile.mkdtemp(prefix="toad-native-tabs-", dir="/var/tmp"))
    print(f"Native terminal evidence: {root}", flush=True)
    os.mkfifo(root / "control", 0o600)
    log = (root / "process.log").open("wb")
    reader, writer = os.pipe()
    server = terminal = connection = None
    control = None
    results = {}

    def wait(name):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            path = root / f"{name}.json"
            if path.exists():
                try:
                    return json.loads(path.read_text())
                except json.JSONDecodeError:
                    pass
            if terminal.poll() is not None:
                raise RuntimeError(f"Terminal exited: inspect {root}")
            time.sleep(.05)
        raise TimeoutError(f"Missing {name} receipt: inspect {root}")

    try:
        server = subprocess.Popen(
            ["Xvfb", "-displayfd", str(writer), "-screen", "0", "2000x1200x24", "-nolisten", "tcp"],
            pass_fds=(writer,), stdout=log, stderr=log, start_new_session=True,
        )
        os.close(writer)
        if not select.select([reader], [], [], 5)[0]:
            raise TimeoutError("Xvfb startup")
        display = ":" + os.read(reader, 32).decode().strip()
        env = dict(os.environ, DISPLAY=display, TMPDIR="/var/tmp", AGENT_COMMS_ROOT=str(root / "wire"),
                   XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                   XDG_DATA_HOME=str(root / "data"))
        for key in ("PYTHONPATH", "AGENT_COMMS_THREAD", "AGENT_COMMS_MANAGED", "PI_AGENT_ID", "PI_PROMPT"):
            env.pop(key, None)
        terminal = subprocess.Popen(
            [terminal_bin, "-g", "125x32+0+0", "-e", sys.executable,
             str(Path(__file__).with_name("native_tab_terminal_app.py")), str(root)],
            env=env, stdout=log, stderr=log, start_new_session=True,
        )
        control = os.open(root / "control", os.O_RDWR | os.O_NONBLOCK)
        ready = wait("ready")
        connection = Display(display)
        window = next(w for w in connection.screen().root.query_tree().children if w.get_wm_class())
        geometry = window.get_geometry()
        hints = window.get_wm_normal_hints()
        cell_width = hints["width_inc"]
        cell_height = hints["height_inc"]
        if cell_width <= 1:
            cell_width = geometry.width // ready["size"][0]
        if cell_height <= 1:
            cell_height = geometry.height // ready["size"][1]
        padding_x = (geometry.width - ready["size"][0] * cell_width) // 2
        padding_y = (geometry.height - ready["size"][1] * cell_height) // 2
        ansi_color = None

        def capture(name, receipt):
            nonlocal ansi_color
            time.sleep(.2)  # Settle actual terminal painting, not a latency claim.
            geometry = window.get_geometry()
            image = ImageGrab.grab(xdisplay=display).crop((
                geometry.x, geometry.y, geometry.x + geometry.width,
                geometry.y + min(geometry.height, 180),
            )).convert("RGB")
            image.save(root / f"{name}.png")
            band = image.crop((padding_x + 21 * cell_width, padding_y + 2 * cell_height,
                               geometry.width - padding_x, padding_y + 3 * cell_height))
            pixels = iter(band.tobytes())
            colors = Counter(zip(pixels, pixels, pixels, strict=True))
            if name == "ready":
                # Learn the actual terminal's ANSI palette from the visible,
                # non-overflowing underline, not Rich's nominal color table.
                ansi_color = colors.most_common(2)[1][0]
            wanted = tuple(receipt["rgb"]) if receipt["rgb"] else ansi_color
            count = colors[wanted]
            results[name] = {**receipt, "underline_pixels": count, "underline_rgb": wanted}
            assert count >= 20, f"Underline absent from actual terminal pixels: {root / (name + '.png')}"
            print(name, count, "underline pixels", flush=True)

        def command(action, name, **values):
            os.write(control, (json.dumps({"action": action, "name": name, **values}) + "\n").encode())
            receipt = wait(name)
            capture(name, receipt)
            return receipt

        capture("ready", ready)
        command("overflow", "overflow")
        command("select", "middle", index=3)
        command("refresh", "repaint")
        command("theme", "ansi", theme="ansi-dark")
        command("theme", "rgb", theme="textual-dark")
        command("select", "first", index=0)

        def mouse(column, row, *actions):
            subprocess.run(["xdotool", "mousemove", "--sync", "--window", str(window.id),
                            str(round(padding_x + column * cell_width)),
                            str(round(padding_y + row * cell_height)), *actions], env=env, check=True)

        mouse(50, 1.5, "click", "1")
        assert command("observe", "real-click")["mode"] == "session-2"
        mouse(35, .5, "mousedown", "1")
        time.sleep(.1)
        mouse(41, .5, "mouseup", "1")
        assert command("observe", "real-drag")["mode"] == "session-2"
        for name, columns in (("narrow", 95), ("wide", 240)):
            subprocess.run(["xdotool", "windowsize", str(window.id),
                            str(columns * cell_width + 2 * padding_x),
                            str(32 * cell_height + 2 * padding_y)], env=env, check=True)
            command("observe", name)
        (root / "results.json").write_text(json.dumps(results, indent=2))
        print(f"PASS: 11 native pixel checks; screenshots in {root}", flush=True)
    finally:
        if control is not None:
            try:
                os.write(control, b'{"action":"exit"}\n')
                terminal.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            os.close(control)
        if connection is not None:
            connection.close()
        for process in (terminal, server):
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        os.close(reader)
        log.close()


if __name__ == "__main__":
    main()
