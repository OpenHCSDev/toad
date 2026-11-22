"""A blocking Core call runs through the preparation owner, never a bare `asyncio.to_thread`.

The default executor is shared: with the Qt loop it has ten workers, and the library's own
reply delivery (`ObservationProcess.receive`, `AsyncWork.run_async`) takes one of them for each
answer. A read waits on a worker for its answer, so ten reads in flight left no worker to
deliver any answer and a tab opened in the meantime never finished (2026-11-22, the tab-strip
drive opening four threads back to back: ten workers blocked in `read_from_thread`, four
`to_thread` jobs queued behind them). `PreparationRuntime.run_thread` admits four at a time,
so a reserve of workers stays free; a bare `to_thread` around a Core call is the bypass.

`NavigationReader.read` offloads `request.read` itself but bounds it with its own slots
(`_slots`); its argument names no Core call, so this pattern does not reach it.
"""

import ast
import re
from pathlib import Path

import toad

SRC = Path(toad.__file__).parent
CORE_CALL = re.compile(r"\bcore\b|\.call\b|\bobserved\b|\bservice\.|acknowledge|historical_threads")

# Each file with its reason it may hand a Core call to `asyncio.to_thread` itself.
ALLOWED = {
    "work_preparation.py": "the owner: `run_thread` is the one place that offloads, behind its slots",
    "submission_queue.py": "`QueueSource.at_owners` is static and holds no path to the owner (one user-initiated "
                           "send or clear at a time)",
}


def bare_to_thread_core_calls(path: Path) -> list[str]:
    source = path.read_text()
    found = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "to_thread" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "asyncio"):
            text = ast.get_source_segment(source, node) or ""
            if CORE_CALL.search(text):
                found.append(f"{path.relative_to(SRC)}:{node.lineno}: {' '.join(text.split())[:100]}")
    return found


def test_no_blocking_core_call_bypasses_the_preparation_owner():
    offenders = [line for path in sorted(SRC.rglob("*.py")) if path.name not in ALLOWED
                 for line in bare_to_thread_core_calls(path)]
    assert not offenders, (
        "a blocking Core call must run through `preparation.run_thread` (or a reader's `call`), "
        "not a bare `asyncio.to_thread`; the shared executor's workers are what deliver Core's "
        "answers:\n" + "\n".join(offenders))


def test_the_allowed_files_still_need_their_exemption():
    """An exemption nobody uses is deleted, not kept."""
    unused = [name for name in ALLOWED
              if not any(bare_to_thread_core_calls(path) for path in SRC.rglob(name))
              and name != "work_preparation.py"]
    assert not unused, f"no raw to_thread Core call left in {unused}: drop them from ALLOWED"
