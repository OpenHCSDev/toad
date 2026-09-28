"""Closing a real pipe with queued native events cancels the observer cleanly."""

import os
from pathlib import Path
from multiprocessing import get_context
import subprocess
import sys
import tempfile

from toad.directory_watcher import _observe_path


def exercise(root: Path):
    context = get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_observe_path, args=(root, child))
    process.start()
    child.close()
    try:
        assert parent.poll(5), "Observer never became ready"
        parent.recv()
        for index in range(512):
            (root / str(index)).touch()
        assert parent.poll(5), "Native burst produced no unread pipe data"
        parent.close()  # Closing with unread events can send RESET, not EOF.
        process.join(3)
        assert process.exitcode == 0, f"Owner loss failed to cancel child: {process.exitcode}"
    finally:
        parent.close()
        if process.is_alive():
            process.kill()
            process.join(3)
        process.close()


def main():
    with tempfile.TemporaryDirectory(prefix="watcher-peer-close-") as directory:
        result = subprocess.run([sys.executable, __file__, directory],
                                capture_output=True, text=True, timeout=12, env=os.environ)
        assert result.returncode == 0, result.stderr
        assert not result.stderr, result.stderr
    print("PASS: 512 real native events queued; peer close cancels child, no thread error, exit0")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        exercise(Path(sys.argv[1]))
    else:
        main()
