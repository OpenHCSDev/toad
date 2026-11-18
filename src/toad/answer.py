from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    from textual.widget import Widget


"""
allow_once - Allow this operation only this time
allow_always - Allow this operation and remember the choice
reject_once - Reject this operation only this time
reject_always - Reject this operation and remember the choice
"""


class Answer(NamedTuple):
    """An answer to a question posed by the agent."""

    text: str
    """The textual response."""
    id: str
    """The id of the response."""
    kind: (
        Literal["allow_once", "allow_always", "reject_once", "reject_always"] | None
    ) = None
    """Enumeration to potentially influence UI"""


type Options = list[Answer]


@dataclass
class Ask:
    """A question for the user, as either frontend's question control shows it: the text, the
    answers to choose from, optional content shown with it, and who hears the answer."""

    question: str
    options: Options
    get_content: Callable[[], Widget] | None = None
    callback: Callable[[Answer], None] | None = None
