"""A prompt that has not composed yet focuses nothing instead of raising.

`Prompt` builds its controls in `compose`, so before mount there is no `Question` and no
editor. `typing_target` answered through `getters.query_one`, which raised

    NoMatches: No nodes match 'Question' on Prompt()

out of `Conversation.initialize_view` → `Prompt.focus()` while a tab was opening
(`NoMatches_2026-11-06T09_47_12_884038.txt`). `enter_insert` above it already answers the
same question with `is_mounted`; this is that answer reaching the other two callers.
"""

from agent_comms.repo import Checkout

from toad.widgets.prompt import MessagePrompt


def test_an_uncomposed_prompt_has_no_typing_target(tmp_path):
    prompt = MessagePrompt(project=Checkout(tmp_path))
    assert prompt.typing_target is None


def test_focusing_an_uncomposed_prompt_focuses_nothing(tmp_path):
    prompt = MessagePrompt(project=Checkout(tmp_path))
    assert prompt.focus() is prompt
