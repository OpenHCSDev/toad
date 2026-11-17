"""The coordination status panel's toolkit-neutral owner.

One reader decodes a `SessionIdentity` and the process-wide agent binary configuration into
a `CoordinationStateReport`. Textual's `CoordinationStatus` widget and Qt's
`QtCoordinationStatus` widget both render from the same report, so the panel's data is
decoded once, in one place, with no per-frontend duplication.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from agent_comms.execution.native_arguments import ConfiguredBinary, InheritedArguments

from toad.thread_identity import SessionIdentity


@dataclass(frozen=True)
class CoordinationStateReport:
    """One snapshot of the coordination wire's identity and the ACP backend it runs under."""

    wire_root: str
    thread_name: str
    backend_name: str
    backend_path: str
    agent_args: str
    root_path: str

    def summary_text(self) -> str:
        """Plain three-line summary — what the panel says, without renderer-specific styling.

        A renderer that adds colour (Textual's `$text` / `$success`) assembles its styled
        version from the component fields; the plain string lives here so both frontends
        agree on what the panel reads as text.
        """
        return (
            f"Wire: {self.wire_root} · persistent\n"
            f"Thread: {self.thread_name}\n"
            f"ACP/session · {self.backend_name}"
        )

    def tooltip_text(self) -> str:
        """The full-detail tooltip; identical on every frontend, so it lives here."""
        return (
            "Messages and threads live on the bus and outlast this window. "
            "This agent runs inside this Toad and stops when it closes.\n\n"
            f"AGENT_COMMS_ROOT={self.root_path}\n"
            f"AGENT_COMMS_AGENT_BIN={self.backend_path}\n"
            f"AGENT_COMMS_AGENT_ARGS={self.agent_args}"
        )


def read_coordination_state(identity: SessionIdentity) -> CoordinationStateReport:
    """Read the three things the coordination panel shows: wire root, open thread, ACP backend.

    `ConfiguredBinary` and `InheritedArguments` are process-wide: the backend binary and its
    arguments were captured when the Toad process started, so they do not change per session
    and are safe to read on every refresh.
    """
    backend = ConfiguredBinary().configured()
    root = identity.root_path
    return CoordinationStateReport(
        wire_root=identity.display_root(),
        thread_name=identity.display_thread(),
        backend_name=Path(backend).name,
        backend_path=backend,
        agent_args=shlex.join(InheritedArguments().configured().argv),
        root_path=str(root) if root is not None else "",
    )
