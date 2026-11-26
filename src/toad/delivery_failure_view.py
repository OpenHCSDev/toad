"""The concrete compose controls used by shared delivery-failure declarations."""


from collections.abc import Awaitable, Callable
from functools import partial

from rich.text import Text as RichText
from textual import getters
from textual.content import Content
from textual.reactive import var
from textual.widget import Widget

from textual.worker import Worker

from toad.app_node import ToadNode
from toad.client.bus_submission import ConversationSubmission, SubmissionView
from toad.client.composer_pool import ComposerDraft, ComposerPoolHost
from toad.client.prompt_composer import ComposerStatus
from toad.client.submission import ComposeAccess
from toad.native_style import StartsHidden
from toad.widgets.flash import Flash
from toad.widgets.prompt import Prompt
from toad.worker_group import InputHistoryRecord


class ComposerPark(StartsHidden, Widget):
    """Hidden workspace slot holding detached pooled composers between tabs so closing a
    tab never unmounts or destroys a reusable composer subtree."""


class DeliveryFailureView(ComposerPoolHost, ComposerStatus, SubmissionView, ToadNode, Widget):
    """The composed input, status and delivery behavior shared by conversations.

    Sending never holds compose: a send waits in the view's submissions, shown above the
    composer, while the owner keeps typing. Only a read-only saved view holds compose."""

    prompt = getters.query_one(Prompt)
    feedback = getters.query_one(Flash)
    status: var[str | Content | RichText] = var("")
    thread_status: var[str | Content | RichText] = var("")
    """The thread's own status from its owner; a read-only block shows over it."""
    composer_block: var[str] = var("")
    """Why compose is held: a read-only saved view; empty when open."""

    def compute_status(self) -> str | Content | RichText:
        return self.composed_status()

    @property
    def active_composer(self) -> Prompt | None:
        return self.query_one_optional(Prompt)

    def workspace_views(self):
        return self.app.workspace_sessions if self.is_attached else None

    def release_pooled_composer(self, composer: Prompt) -> ComposerDraft:
        draft = composer.capture_composer_draft()
        if self.is_attached and composer.pool_alive():
            if (park := self.screen.query_one_optional(ComposerPark)) is not None:
                composer.reparent(park)
        return draft

    async def refresh_composer(self, access: ComposeAccess) -> None:
        """Draw compose from the caller's Core answer."""
        if not self.is_attached:
            return
        reason = access.block_reason
        self.composer_block = reason

        def apply(prompt: Prompt) -> None:
            prompt.offer_files(access.takes_files)
            area = prompt.prompt_text_area
            area.disabled = bool(reason)
            area.tooltip = reason or None
            if not area.disabled and self.screen.focused is None:
                self.screen.set_focus(area)

        self.on_composer("access", apply)

    @property
    def submission_composer(self):
        """The prompt a returned draft goes back into. A send whose outcome is unknown comes
        back too: the owner sees whether it landed in this view, rather than waiting on an
        answer it cannot get."""
        return self.active_composer

    def restore_composer_draft(self, text: str) -> None:
        self.on_composer("draft", lambda prompt: prompt.restore_draft(text))

    def show_send_failure(self, text: str) -> None:
        self.feedback.flash(text, style="error")

    def record_input(self, text: str) -> None:
        InputHistoryRecord.run_on(self, partial(self.input_histories.prompt.record, text))

    def run_submission(self, send: Callable[[], Awaitable[None]]) -> Worker[None]:
        return self.run_worker(send, group=ConversationSubmission.group)

    def submissions_changed(self) -> None:
        self.on_composer("queue", lambda prompt: prompt.sync_queue())
