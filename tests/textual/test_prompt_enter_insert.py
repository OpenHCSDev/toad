"""Textual-facing: vim `i` asks the prompt for insert mode; the prompt owns whether its editor exists."""

from agent_comms.repo import Checkout
from toad.widgets.prompt import MessagePrompt


def test_enter_insert_before_compose_has_no_editor_to_touch(tmp_path):
    MessagePrompt(project=Checkout(tmp_path)).enter_insert()
