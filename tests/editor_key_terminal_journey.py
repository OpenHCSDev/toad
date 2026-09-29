"""Real LinuxDriver mouse and escape-key delivery through the existing PTY owner."""
import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from e2e_pty import PtyLaunch, ToadSession
from first_frame_installed_terminal_journey import until


async def main():
    evidence = Path(os.environ["EDITOR_KEY_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="editor-terminal-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        env = dict(os.environ, AGENT_COMMS_ROOT=str(root / "wire"),
                   XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
                   XDG_STATE_HOME=str(root / "state"), TOAD_TEST_ATTEMPT=root.name)
        env["PYTHONPATH"] = os.pathsep.join(
            str(Path(path).resolve()) for path in env.get("PYTHONPATH", "").split(os.pathsep) if path
        )
        for key in ("AGENT_COMMS_THREAD", "AGENT_COMMS_MANAGED", "PI_AGENT_ID", "PI_PROMPT", "NO_COLOR"):
            env.pop(key, None)
        command = (sys.executable, str(Path(__file__).with_name("editor_key_workflow_pilot.py")),
                   "--terminal", str(root), str(evidence))
        session = ToadSession(PtyLaunch(command, root, env))
        phases = []

        def state():
            session._screen()  # Consume real terminal writes; a PTY must not backpressure the UI.
            return json.loads((evidence / "current-ui.json").read_text())

        async def expect(label, text, cursor):
            await until(lambda: state()["text"] == text and state()["cursor"] == [0, cursor], session, 5)
            observed = state()
            assert observed["editor_focused"] and observed["driver"] == "LinuxDriver", observed
            phases.append({"phase": label, **observed})

        async def edits(label):
            current = state()
            x, y, _, _ = current["editor_region"]
            await session.click(x + 2, y + 1)
            await session.type_text("abcd")
            await expect(label + "-typed", "abcd", 4)
            await session.send(b"\x1b[D")
            await expect(label + "-left", "abcd", 3)
            await session.send(b"\x7f")
            await expect(label + "-backspace", "abd", 2)
            await session.send(b"\x1b[3~")
            await expect(label + "-delete", "ab", 2)
            await session.send(b"\x1b[D\x1b[C")
            await expect(label + "-arrows", "ab", 2)
            await session.send(b"\x7f\x7f")
            await expect(label + "-empty", "", 0)

        try:
            await session.start()
            await until(lambda: (evidence / "ready").exists(), session)
            await edits("clicked")
            await session.send(b"\x1b\t\x1b[Z")
            await edits("traversal")
            tabs = state()["tabs"]
            assert len(tabs) == 2
            for index in (0, 1, 0):
                target = tabs[index]
                x, y, width, _ = target["region"]
                await session.click(x + max(1, width // 2), y + 1)
                await until(lambda: state()["source"] == target["source"], session, 5)
                await edits("return-" + target["source"])
            (evidence / "terminal-key-phases.json").write_text(json.dumps(phases, indent=2) + "\n")
            await session.send(b"\x11")
            await asyncio.wait_for(session.proc.wait(), 6)
            assert session.proc.returncode == 0
            print("REAL_LINUXDRIVER_MOUSE_ABA_TYPING_LEFT_RIGHT_BACKSPACE_DELETE_PASS")
        finally:
            (evidence / "terminal-key-phases.json").write_text(json.dumps(phases, indent=2) + "\n")
            (evidence / "terminal-visible.txt").write_text(session._screen())
            (evidence / "terminal-output.txt").write_bytes(session.buffer)
            await session.stop()


if __name__ == "__main__":
    asyncio.run(main())
