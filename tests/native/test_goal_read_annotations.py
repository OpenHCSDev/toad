"""Native owner reads expose the original captured-read result at runtime."""

from typing import get_type_hints

import pytest

from toad.acp.comms_updates import PendingThreadRead
from toad.acp.session_agent import OwnerReads
from toad.goal_interaction import GoalSession
from toad.target_commands import TargetContext
from toad.widgets.conversation import Conversation


@pytest.mark.parametrize("callback", (OwnerReads.owner_read, OwnerReads.thread_read))
def test_native_owner_read_result(callback):
    assert get_type_hints(callback)["return"] is PendingThreadRead


def test_command_target_read_result():
    assert get_type_hints(Conversation.command_target_context)["return"] is TargetContext


def test_goal_session_view_contract():
    assert get_type_hints(GoalSession.__init__)["view"]


def test_goal_session_modal_contract():
    assert get_type_hints(GoalSession.present)["modal"]
