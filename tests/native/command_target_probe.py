"""Record the real command screen's MRO and determining property owners."""

import importlib
import json
import sys

importlib.import_module(sys.argv[1])

from toad.screens.main import MainScreen
from toad.widgets.conversation import Conversation
from toad.widgets.goal_bar import GoalBar


def declaration_name(declaration: type) -> str:
    return f"{declaration.__module__}.{declaration.__qualname__}"


print(json.dumps({
    "mro": [declaration_name(parent) for parent in MainScreen.__mro__],
    "conversation_mro": [declaration_name(parent) for parent in Conversation.__mro__],
    "bar_mro": [declaration_name(parent) for parent in GoalBar.__mro__],
    "owners": {
        name: declaration_name(next(parent for parent in MainScreen.__mro__ if name in vars(parent)))
        for name in ("navigation_context", "thread_identity", "navigation_owner", "prepare_presentation", "retire_presentation")
    },
}, indent=2))
