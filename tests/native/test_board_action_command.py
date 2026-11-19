"""The two Team frontends share Core's nominal board-action projection."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

from agent_comms.nominal.text_digest import TextDigest
from agent_comms.registry.thread_identity import RecordedThreadIncarnation
from agent_comms.task_attachments.team_pings import RulePing, TeamUpdateNotice
from agent_comms.team import judge
from agent_comms.team.board_actions import BoardActionApplied
from agent_comms.team.order import TeamVerbActionOffer
from agent_comms.team.standing_rules import OrderlessUnreviewedHead
from agent_comms.team.team_hud import TeamHud
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tools.orders import CommsBoardActionTool

from toad.target_commands import BoardCommand


@dataclass
class CapturingCore:
    request: CommsBoardActionTool | None = None

    def call(self, request: CommsBoardActionTool) -> BoardActionApplied:
        self.request = request
        return BoardActionApplied(("applied once",))


def test_board_command_binds_the_shared_packet_offer_to_its_recipient() -> None:
    recipient = RecordedThreadIncarnation("reviewer", 1.0)
    observation = TextDigest.of("shared board source")
    offer = TeamVerbActionOffer(
        judge.OkVerb,
        ("--repo", "openhcsdev/agent-comms", "--pr", "7", "--head", "a" * 40),
        observation,
    )
    ping = RulePing(
        OrderlessUnreviewedHead,
        observation,
        text="Review the exact head",
        offers=(offer,),
    )
    packet = TeamUpdateNotice(recipient, (ping,))
    hud = cast(TeamHud, SimpleNamespace(teammate=recipient, packets=(packet,)))

    command, = BoardCommand.for_hud(hud)

    assert command.offer == offer.bind(recipient)


def test_board_command_projects_the_owned_offer_without_another_registry() -> None:
    offer = TeamVerbActionOffer(
        judge.OkVerb,
        ("--repo", "openhcsdev/agent-comms", "--pr", "7", "--head", "a" * 40),
        TextDigest.of("current board source"),
        RecordedThreadIncarnation("reviewer", 1.0),
    )
    command = BoardCommand(offer)
    core = CapturingCore()
    assert command.label == judge.OkVerb.help
    assert command.execute(cast(CoreAccess, core)) == BoardActionApplied(("applied once",))
    assert core.request == CommsBoardActionTool(offer=offer)
