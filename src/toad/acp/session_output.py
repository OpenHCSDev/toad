"""Original output evidence outlives its optional native presentation."""

from agent_comms.transcripts import NativeCommittedPrefix

from toad.widgets.committed_presentation import CapturedClaim


class SessionOutput:
    def __init__(self) -> None:
        self.assistant = CapturedClaim()
        self.committed_source: NativeCommittedPrefix | None = None

    def assistant_committed(self, source: NativeCommittedPrefix) -> None:
        self.assistant.source = source
        self.assistant = CapturedClaim()

    def round_committed(self, source: NativeCommittedPrefix) -> None:
        self.committed_source = source
