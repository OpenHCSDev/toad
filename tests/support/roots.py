"""The private directories one test works in."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile

ATTEMPT = "TOAD_TEST_ATTEMPT"


@dataclass(frozen=True)
class Roots:
    """One disposable directory holding the wire, the settings and the project of a test."""

    attempt: Path

    @classmethod
    def create(cls) -> Roots:
        # tempfile owns the configured scratch location, including TMPDIR.
        return cls(Path(tempfile.mkdtemp(prefix="toad-test-")))

    @classmethod
    def of_this_process(cls) -> Roots:
        """The roots the test runner gave this process."""
        return cls(Path(os.environ[ATTEMPT]))

    @property
    def wire(self) -> Path:
        return self.attempt / "wire"

    @property
    def project(self) -> Path:
        return self.attempt / "project"

    def environment(self, inherited: dict[str, str]) -> dict[str, str]:
        """The environment of a process that may only touch these roots."""
        env = {key: value for key, value in inherited.items()
               if not key.startswith("AGENT_COMMS_") and key != "NO_COLOR"}
        env.update({
            ATTEMPT: str(self.attempt),
            "AGENT_COMMS_ROOT": str(self.wire),
            "XDG_CONFIG_HOME": str(self.attempt / "config"),
            "XDG_DATA_HOME": str(self.attempt / "data"),
            "XDG_STATE_HOME": str(self.attempt / "state"),
            "XDG_CACHE_HOME": str(self.attempt / "cache"),
            "PI_CODING_AGENT_DIR": str(self.attempt / "pi"),
            "TMPDIR": str(self.attempt),
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "FORCE_COLOR": "1",
        })
        return env
