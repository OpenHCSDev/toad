"""Real LinuxDriver mouse and escape-key delivery through the existing PTY owner."""
import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from e2e_pty import PtyLaunch, ToadSession
from first_frame_installed_terminal_journey import until


async def main(saved_history=False):
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
                   "--terminal-history" if saved_history else "--terminal", str(root), str(evidence))
        session = ToadSession(PtyLaunch(command, root, env))
        phases = []

        def state():
            session._screen()  # Consume real terminal writes; a PTY must not backpressure the UI.
            return json.loads((evidence / "current-ui.json").read_text())

        async def expect(label, text, cursor):
            def ready():
                observed = state()
                return (observed["text"] == text and observed["cursor"] == [0, cursor]
                        and observed["editor_focused"])
            await until(ready, session, 5)
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
            # One real terminal read can contain several keys before deferred
            # Widget.focus() runs. Printable forwarding from the transcript
            # must establish the editor's binding chain in the same handoff.
            x, y, width, height = state()["window_region"]
            await session.click(x + width // 2, y + height // 2)
            await until(lambda: state()["focused"] == "Window", session, 5)
            phases.append({"phase": "transcript-focused", **state()})
            await session.send(b"abcd\x1b[D\x7f\x1b[3~")
            await expect("transcript-key-burst", "ab", 2)
            if saved_history:
                await session.send(b"\x7f\x7f")
                await expect("prepare-saved-history-reader", "", 0)
                # Physical PageUp drives the real source/page/worker admission;
                # no editor/loading flag or view implementation is substituted.
                await session.click(x + width // 2, y + height // 2)
                await session.send(b"\x1b[5~" * 6)
                await until(lambda: "WorkingTranscript" in state()["source_work"], session, 5)
                current = state()
                x, y, _, _ = current["editor_region"]
                await session.click(x + 2, y + 1)
                await session.send(b"draftabcd\x1b[D\x7f\x1b[3~\x1b[D")
                await expect("saved-load-draft-and-caret", "draftab", 6)
                retained = state()
                home = retained["source"]
                other = next(tab for tab in tabs if tab["source"] != home)
                x, y, width, _ = other["region"]
                await session.click(x + max(1, width // 2), y + 1)
                await until(lambda: state()["source"] == other["source"], session, 5)
                await session.send(b"other\x1b[D")
                await expect("saved-load-other-draft", "other", 4)
                target = next(tab for tab in tabs if tab["source"] == home)
                x, y, width, _ = target["region"]
                await session.click(x + max(1, width // 2), y + 1)
                await until(lambda: state()["source"] == home, session, 5)
                await expect("saved-load-return-draft-caret", "draftab", 6)
                assert (state()["document"], state()["history"]) == \
                    (retained["document"], retained["history"])
                await session.send(b"\x1a")
                await expect("saved-load-return-undo", "draftabcd", 8)
                await session.send(b"\x7f\x1b[3~\x1b[D\x1b[C")
                await expect("saved-load-return-delete-arrows", "draftab", 7)
                trace = json.loads((evidence / "key-trace.json").read_text())
                assert any(row.get("key") in {"backspace", "delete", "left", "right"}
                           and "WorkingTranscript" in row["source_work"] for row in trace), \
                    "Editing keys did not overlap an actual source operation"
            (evidence / "terminal-key-phases.json").write_text(json.dumps(phases, indent=2) + "\n")
            await session.send(b"\x11")
            def exited():
                session._screen()
                return session.proc.returncode is not None
            await until(exited, session, 6)
            assert session.proc.returncode == 0
            print("REAL_LINUXDRIVER_MOUSE_ABA_TYPING_LEFT_RIGHT_BACKSPACE_DELETE_PASS")
        finally:
            (evidence / "terminal-key-phases.json").write_text(json.dumps(phases, indent=2) + "\n")
            (evidence / "terminal-visible.txt").write_text(session._screen())
            (evidence / "terminal-output.txt").write_bytes(session.buffer)
            await session.stop()


if __name__ == "__main__":
    asyncio.run(main(saved_history=sys.argv[1:] == ["--saved-history"]))
