"""The Qt thread layer: a conversation that shows a bound thread's transcript.

Both `QtAcpSessionView` (live Claude-CLI session) and `QtMailboxView` (saved mailbox thread
opened through `thread_navigation.open`) are a `QtConversation` whose history is a
`QtTranscriptHistory` bound to a `TranscriptPresentation`: the transcript publishes through
`BoundView`, so this layer answers `BoundViewHost`, and under it sit the rows Textual's
`Conversation.compose` mounts for a thread (session status, goal bar, prompt). The channel
tab, `ConversationView`, is the other `QtConversation`: its wire history publishes no
transcript.
"""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Iterable, Sequence
from typing import TYPE_CHECKING, ClassVar

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine
from ui_theme.scheme import ForegroundColour

from agent_comms.ui_model.delivery import DeliveryView
from toad.command_catalog import AddressesItsThread
from toad.client.draft_fragments import DRAFT_FRAGMENTS
from toad.client.history_rows_view import settled
from toad.client.transcript_history_contract import TranscriptHistoryContract
from toad.navigation_context import NavigationOwner, ThreadViewNavigation
from toad.qt.bound_view import QtBoundViewHost
from toad.qt.composer import Composer
from toad.qt.conversation import QtConversation
from toad.qt.goal import QtGoalBar
from toad.qt.transcript_fragments import QT_FRAGMENT_CLASSES
from toad.qt.metrics import UiGap
from toad.qt.prompt_stack import QtInputDeliveryDetails, QtSessionDetails
from toad.qt.question import QtQuestion
from toad.qt.transcript_history import QtTranscriptHistory
from toad.transcript_publication import BoundView

if TYPE_CHECKING:
    from toad.client.session_tracker import SessionDetails
    from toad.transcript_scope import TranscriptScope
    from toad.qt.window import QtToadApp


class QtThreadView(
    AddressesItsThread,
    QtConversation,
    ThreadViewNavigation,
    QtBoundViewHost,
    NavigationOwner,
    metaclass=PyQtWidgetMeta,
):
    """A `QtConversation` showing one bound thread's transcript.

    Subclasses MUST assign `self.app` before calling `self._lay_out_thread(...)`, and
    answer `thread_identity` and `mode`.

    The transcript stack (`message_history` over `transcript`), the `BoundViewHost`
    contract, the column (`_lay_out_thread`: title, transcript, then the thread's rows
    under it) and the transcript scope are owned here, so the two thread-bound views share
    one implementation.
    """

    # ---- Shared contract: the rows Textual's `Conversation.compose` mounts for a thread ----
    #
    # Under the transcript Textual yields `Flash`, then its `PromptStack`: the activity
    # sweep (`throbber_above`), the session-status disclosure (`thread_activity`), the
    # goal bar and the prompt (with its info bar). `_lay_out_thread` builds the Qt sibling
    # of each in that order; until it has, the view has none of them.

    identity_line: ElidedLine | None = None
    """The title row every thread view shows at the top of its column."""
    thread_activity: QtSessionDetails | None = None
    """Textual's `OperationalSessionDetails`: ``▶ <status> · …`` over its details."""
    goal_bar: QtGoalBar | None = None
    """Textual's `GoalBar`; `None` for a view with no managed thread to own a goal."""

    @abstractmethod
    def composer_class(self) -> type[Composer]:
        """The composer this view kind mounts (Textual's `operational_sources.prompt`)."""

    @property
    @abstractmethod
    def composer_label(self) -> str:
        """What the composer's placeholder names."""

    def sync_working(self) -> None:
        """Textual's `Conversation._turn_changed`: the sweep, then the session details
        read the observed row again."""
        super().sync_working()
        self.thread_activity.refresh_summary()

    def inspect_session(self) -> None:
        """Textual's `Conversation.inspect_session`: the session details over the view, the
        overview from the status row."""
        QtInputDeliveryDetails(
            self, self.app.renderer, self.thread_activity.overview(), DeliveryView()).open()

    def _lay_out_thread(self, app: QtToadApp, title: str, incarnation) -> None:
        """Build the view's column: `title` centred over the transcript, and under it the
        rows of `_setup_prompt_stack` for `incarnation` (None for a view with no managed
        thread, which has no goal bar). Call from the subclass `__init__` after
        `super().__init__()` and after assigning `self.app`."""
        self._setup_transcript(app)
        self.identity_line = ElidedLine(title)
        self.identity_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app.renderer.themed(self.identity_line, lambda: self.identity_line.setStyleSheet(
            f"color: {ForegroundColour.rgb(app.renderer.scheme).hex};"))
        info = QHBoxLayout()
        info.setContentsMargins(UiGap.loose, UiGap.normal, UiGap.loose, UiGap.normal)
        info.addWidget(self.identity_line, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(info)
        layout.addWidget(self.messages, 1)
        # Under the transcript, Textual's order: flash, sweep, status, goal, prompt.
        self._setup_prompt_stack(app, layout, incarnation)

    def transcript_scope(self) -> TranscriptScope:
        """The transcript scope this view is bound to: its thread identity owns it.
        `BoundView.thread_scope` reads it on bind to observe the thread."""
        return self.thread_identity.transcript_scope()

    def _setup_transcript(self, app: QtToadApp) -> None:
        """Build the conversation and its transcript stack, as `_lay_out_thread` does first.

        `TranscriptPresentation` (made by `_setup_conversation`) comes before
        `QtTranscriptHistory`: the history reads `view.transcript.get_transcript_page`
        during construction to build its `SavedTranscript`.
        """
        self._setup_conversation(app)
        # `NativeSessionEntry.__call__` writes this on tabs that go through the
        # entry; mailbox opens through `replace_opening_view` instead.
        self.session_details: SessionDetails | None = None
        # `QtTranscriptHistory` mirrors Textual's `TranscriptHistory` — same
        # `CommittedHistoryBase` + `ReportsCoveredPages` bases, same `SavedTranscript`
        # source over `view.transcript.get_transcript_page`, same page type
        # (`PreparedTranscriptPage`). Tool calls, sent messages, Claude chunks and
        # context events all feed in through this one source.
        self.message_history = QtTranscriptHistory(self.messages, self, app)

    def _mount_transcript(self) -> None:
        """Bind the transcript once and mount its history, in Textual's mount order:
        `Conversation.on_mount` binds, then `TranscriptHistory.on_mount` observes the source
        and lets the history's state schedule its first page through `BoundView`.

        The selected-page lifecycle calls this after navigation has attached the Qt widget
        and bound a mailbox identity.  The binding itself is the mounted-state authority:
        restored selections do not mount a second history."""
        if self.transcript.binding.matches(self):
            return
        if not self.is_attached:
            return
        self.transcript.bind(self)
        self.attach_history(self.message_history)
        for row in self.activity:
            row.mount()

    def activate_selected_thread(self) -> None:
        """Activate state specific to a selected thread kind.

        A mailbox has no native agent to attach.  The ACP member overrides this one
        difference; mounting, refreshing and publishing remain one inherited lifecycle.
        """

    def shown(self, window, visited) -> None:
        """Attach and publish the selected thread through one nominal lifecycle.

        A zero-delay timer cannot represent attachment: on Android it could run before the
        restored widget had a parent, return, and leave history blank until a later message
        caused another publication.  Page selection is the actual attachment boundary.
        """
        if self.session_details is not None:
            visited(self.session_details.identity)
        self._mount_transcript()
        self.activate_selected_thread()
        self.reload()
        self.publish_selected_thread()

    def _setup_prompt_stack(self, app: QtToadApp, layout: QVBoxLayout, incarnation) -> None:
        """Mount, under the transcript, the rows Textual's `Conversation.compose` yields
        after its window, in its order: flash, sweep, session status, goal bar, prompt.

        The composer is built once the transcript has painted (`reserve_composer`); its
        slot is reserved here so it lands in order, with the question under it."""
        self.thread_activity = QtSessionDetails(self, app.renderer)
        self.goal_bar = None if incarnation is None else QtGoalBar(app, app.renderer, incarnation)
        self.activity = tuple(row for row in (self.thread_activity, self.goal_bar) if row is not None)
        self._composer_slot = QVBoxLayout()
        self._composer_slot.setContentsMargins(0, 0, 0, 0)
        for row in (self.feedback, self.agent_activity, *self.activity):
            layout.addWidget(row)
        layout.addLayout(self._composer_slot)
        self.refresh_thread_status()
        self.reserve_composer(self._composer_slot, lambda: self.composer_class()(self, app.renderer),
                              partial(self._composer_mounted, app))

    def _composer_mounted(self, app: QtToadApp, composer: Composer) -> None:
        # Under the composer, as on a channel: the question an agent asks (a permission, a
        # confirmation), hidden until asked.
        self.question = QtQuestion(app, self)
        self._composer_slot.addWidget(self.question)
        composer.labelled(self.composer_label)
        self.sync_status()

    def command_target_scope(self) -> QtThreadView:
        """The view holds its own thread identity and navigation, where Textual's asks the
        screen that presents it."""
        return self

    # ---- BoundViewHost contract ----

    MAX_LIVE_BLOCKS: ClassVar[int] = 1
    """Every refresh attempts commit; `CommitEvidence` retires only live blocks covered by saved history."""

    @property
    def transcript_history(self) -> TranscriptHistoryContract:
        """`BoundViewHost.transcript_history`: the single transcript-page-producing
        child `BoundView` drives. `QtTranscriptHistory` satisfies the contract
        through the shared `CommittedHistoryBase` + `ReportsCoveredPages` bases."""
        return self.message_history

    # ---- BoundViewHost: Qt draws the blocks as rows of its one history model ----

    @property
    def live_blocks(self) -> tuple[object, ...]:
        return (self.transcript_history, *self.messages.live_blocks)

    def retire_blocks(self, blocks: Sequence[object]) -> Awaitable[None]:
        if not blocks:
            return settled()

        async def _retire() -> None:
            await self.output.retire_presentations(blocks)
            self.messages.retire_live(blocks)

        return _retire()

    def protected_blocks(self, candidates: Iterable[object]) -> set[object]:
        return set()

    def blocks_in_viewport(self, candidates: Sequence[object]) -> bool:
        return self.messages.live_in_viewport(candidates)

    def later_history(self, page, source, conversation_order: int):
        raise ValueError("Qt thread views draw live entries as history rows, so history never splits")

    def show_draft(self, draft, identity) -> None:
        self.messages.show_draft(DRAFT_FRAGMENTS.project_value(draft, identity, QT_FRAGMENT_CLASSES))

    def empty_history(self) -> QtTranscriptHistory:
        return QtTranscriptHistory(self.messages, self, self.app)

    def attach_history(self, history) -> None:
        """The history becomes the view's one history: it observes its source and its state
        schedules the first page. Qt applies this at once, so there is nothing to wait for."""
        self.message_history = history
        history.observe_source()
        history.state.mounted(history)

    def mount_history(self, history, *, before=None):
        """`BoundViewHost.mount_history`: `BoundView` awaits the mount it asks for."""
        self.attach_history(history)
        return settled()

    def remove_history(self, history):
        history.close()
        return settled()

    def refresh_session_summary(self) -> None:
        self.thread_activity.refresh_summary()

    def resume_retained_history(self) -> None:
        self.message_history.state.resume_if_parked(self.message_history)

    def transcript_binding(self) -> BoundView:
        """Called by `ViewBinding.bound_to(view)` on `TranscriptPresentation.bind`: a
        thread publishes its transcript through this view, as Textual's
        `Conversation.transcript_binding`."""
        return BoundView(self)

    # ---- ThreadViewNavigation ----

    @property
    def navigation_mode(self) -> str:
        return self.mode

    @property
    def coordination_root(self) -> str | None:
        """The bus root this view's thread is read from, as `SessionScope` answers it."""
        return self.thread_identity.wire_root()
