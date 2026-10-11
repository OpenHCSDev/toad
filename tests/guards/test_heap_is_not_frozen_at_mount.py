"""The application does not freeze the heap when it mounts; the first shown history does (see tests/textual/test_heap_freezes_once.py)."""

from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src/toad/app.py"


def test_application_start_does_not_freeze():
    mount = SOURCE.read_text().split("async def on_mount(self) -> None:")[1].split("\n    def ")[0]
    assert "gc.freeze" not in mount
