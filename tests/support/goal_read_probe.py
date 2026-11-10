"""Resolve source-bound goal contracts after one requested cold import."""

import importlib
import json
import sys
from typing import get_origin, get_type_hints

importlib.import_module(sys.argv[1])

from toad.goal_interaction import GoalInteraction, GoalSession
from toad.goal_view import GoalCollapse, GoalView
from toad.widgets.conversation import Conversation
from toad.widgets.goal_bar import GoalBar

assert get_origin(get_type_hints(GoalSession.__init__)["view"]) is GoalView
assert get_type_hints(GoalSession.present)["modal"]
assert issubclass(Conversation, GoalView)
assert issubclass(GoalBar, GoalCollapse)
print(json.dumps({
    "first_module": sys.argv[1],
    "members": sorted(member.declared_name for member in GoalInteraction.members_with(GoalInteraction)),
}))
