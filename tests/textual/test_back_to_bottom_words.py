"""Textual-facing: the jump button shows its action's own words, not a second copy of them."""

from toad.view_actions import BackToBottomAction
from toad.widgets.conversation import BackToBottom, Window


async def test_the_jump_button_draws_its_actions_title_and_key(workspace):
    """Compared against the declaration, not against a literal: a button that spells the
    words itself fails here the moment the action's title or key display changes."""
    async with workspace.app(size=(120, 40)) as ui:
        app, _pilot = ui.textual
        button = app.screen.query_one(Window).jump_bar.query_one(BackToBottom)
        assert str(button.content) == (
            f"{BackToBottomAction.title}\n↓ {BackToBottomAction.key_display} ↓")
        assert BackToBottomAction.key_display in str(button.content)
        assert str(button.content).count("\n") == 1, "two rows, so the key sits under the name"
