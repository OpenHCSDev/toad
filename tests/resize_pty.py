"""Exercise full terminal damage/repaint across large real SIGWINCH transitions."""

import asyncio
import json
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from e2e_pty import AGENT_PY, FORK_TOAD, PtyLaunch, ToadSession


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-resize-pty-") as directory:
        root = Path(directory)
        history = root / "session.jsonl"
        history.write_text("".join(json.dumps({"type": "message", "message": {
            "role": "assistant", "content": f"REPLAY_MARKER_{i}\n\n" + "A paragraph to wrap. " * 100
        }}) + "\n" for i in range(40)))
        comms = wire(root / "wire")
        comms.register(Thread("resize", frozenset(), str(root), session_file=str(history)))
        session = ToadSession(PtyLaunch(
            (str(FORK_TOAD), "acp", f"{AGENT_PY} -m agent_comms.acp", "--session", "resize"),
            root,
            {"AGENT_COMMS_ROOT": str(root / "wire"), "AGENT_COMMS_AGENT_BIN": "/bin/echo",
             "AGENT_COMMS_AGENT_MODELS": "test/model", "AGENT_COMMS_AGENT_ARGS": "--model test/model",
             "XDG_CONFIG_HOME": str(root / "config"), "XDG_STATE_HOME": str(root / "state"),
             "XDG_DATA_HOME": str(root / "data")},
        ))
        try:
            await session.start()
            for height, width in ((25, 70), (28, 145), (25, 70), (50, 180), (35, 95), (25, 70)):
                session._set_size(height, width)
                frame = await session.frame(.7)
                assert "A paragraph" in frame or "REPLAY_MARKER_39" in frame, (width, height, frame)
                assert "Channels" in frame and "❯" in frame, (width, height, frame)
                assert session.alive()
            print("PTY resize: transcript, sidebar, and composer repaint across fullscreen transitions")
        finally:
            await session.stop()


if __name__ == "__main__":
    asyncio.run(main())
