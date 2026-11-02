"""Exit before answering the real handshake; the foreign descendant remains."""
import os

from acp.schema import NewSessionResponse
from retirement import RetirementPeer


class ExitingRetirementPeer(RetirementPeer):
    def after_child(self, response: NewSessionResponse) -> NewSessionResponse:
        os._exit(0)


if __name__ == "__main__":
    ExitingRetirementPeer.main()
