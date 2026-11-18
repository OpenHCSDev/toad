"""What a conversation shows for one agent turn, for every frontend.

The shared turn code decides *what* appears: a user's input row once the turn starts, a
response or thought block that streams fragments, an error note, a help note, a link to
the agent's log. It never builds a toolkit widget. Each frontend's conversation view
answers these hooks with its own drawing: Textual mounts its blocks, Qt draws rows
through the shared fragment pipeline.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.response_delivery import ResponseDelivery

    from toad.live_output import OutputStream


class LiveBlock:
    """One block of a turn while its fragments stream in. Plain mixin, like `TurnPresentation`.

    `source_claim` is the captured claim of the stream that opened it, so a saved
    history that later covers the block can retire it. `loading` is true while the
    block has nothing to show yet; a thought that never received text is removed
    when its turn settles.
    """

    source_claim: object

    @property
    @abstractmethod
    def loading(self) -> bool: ...

    @abstractmethod
    async def append_fragment(self, fragment: str) -> None: ...

    @abstractmethod
    async def finish_stream(self) -> None: ...

    @abstractmethod
    async def remove(self) -> None: ...


class TurnPresentation:
    """The hooks a conversation view answers for the shared turn code.

    Plain mixin, no ABC base: Textual's `Conversation` and Qt's conversation views each
    carry their own toolkit metaclass, and both list this beside it."""

    @property
    @abstractmethod
    def shows_live_output(self) -> bool:
        """Whether the view is still on screen to take live output."""

    @abstractmethod
    def after_live_output(self, finish: Callable[[], Awaitable[object]]) -> None:
        """Run `finish` once the view has handled the output already queued."""

    @abstractmethod
    async def present_user_input(self, text: str) -> None:
        """Show the user's input as the turn's opening row."""

    @abstractmethod
    def response_block(self, fragment: str, delivery: ResponseDelivery) -> LiveBlock:
        """A new response block holding `fragment`, not yet shown."""

    @abstractmethod
    def thought_block(self, fragment: str) -> LiveBlock:
        """A new thought block holding `fragment`, not yet shown."""

    @abstractmethod
    async def show_live_block(self, block: LiveBlock, stream: OutputStream) -> None:
        """Show `block`, opened by `stream`, after the turn's earlier output."""

    @abstractmethod
    async def present_error_note(self, message: str, details: str) -> None:
        """An agent failure: `message` is markup, `details` plain text (either may be empty)."""

    @abstractmethod
    async def present_help_note(self, markdown: str) -> None:
        """Help that follows a failure, as Markdown."""

    @abstractmethod
    async def present_log_link(self, markdown: str) -> None:
        """A link to the agent's log, as Markdown, outside any message's divider."""
