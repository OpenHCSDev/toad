"""Qt sibling of Textual's `AboveThrobber`: the activity sweep above an ACP transcript
that animates while the bound agent's current turn is busy.

Shared state owner: `ConversationTurn` + `TurnOwner.busy` (`toad.conversation_turn`).
Textual's `Conversation.throbber_above = AboveThrobber(self.working)` reads the SAME
`self.turns.owner.busy` through its `ConversationTurn`; Qt reads it through a
`ConversationTurn` instantiated on `QtAcpSessionView` and refreshes on `TurnChangedUpdate`
Core events (the same event Textual's `on_turn_changed` handler at
`conversation_comms_handlers.py:73` subscribes to via `@handles`). The visual —
`ActivitySweep` using the shared `ACTIVITY_SWEEP` ribbon from `ui_theme.effects` — is
already toolkit-neutral; this widget simply mounts it above the transcript and gates
its animation on the shared busy state.
"""

from __future__ import annotations

from functools import partial

from agent_comms.acp_extension import TurnChangedUpdate
from PySide6.QtWidgets import QVBoxLayout, QWidget

from toad.client.subscribers import CallbackSubscription
from toad.conversation_turn import ConversationTurn, TurnOwner
from toad.qt.activity import ActivitySweep
from toad.qt.core_events import QtCoreObserver
from toad.qt.lines import QtLineRenderer


class QtAgentActivity(QtCoreObserver, QWidget):
    """The activity sweep an ACP session view mounts above its transcript.

    `host` must expose `app` (ClientApplication), `agent_binding` (AgentConnection with a
    `.presentation.turns` TurnBinding). Subscribing to `TurnChangedUpdate` via the shared
    `QtCoreObserver` → `observe_core_callback` keeps the busy answer live without a Qt
    timer polling the agent state."""

    def __init__(self, host, renderer: QtLineRenderer) -> None:
        super().__init__()
        self._host = host
        self.app = host.app
        self._strip = ActivitySweep(renderer)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._strip)
        self._turns = ConversationTurn(self._turn_changed, self._read_turns)
        self._attached = False

    def _read_turns(self):
        """Read the agent's current TurnBinding; a disconnected session has an idle turn
        because `NoAgentConnection.presentation` is a `LocalAgentPresentation` whose
        `turns` is a `LocalTurnBinding(None)`."""
        return self._host.agent_binding.presentation.turns

    @property
    def coordination(self):
        return self.app.coordination_access

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._attached:
            self._attached = True
            self.observe_core_callback(
                self.coordination.events,
                TurnChangedUpdate,
                self._on_turn_changed_event,
                factory=CallbackSubscription,
            )
            # Prime the sweep against the current state in case a turn is already busy.
            self._turn_changed(self._turns.owner)

    def _on_turn_changed_event(self, event: TurnChangedUpdate) -> None:
        """Core published a TurnChangedUpdate: re-read the owner and refresh the sweep.

        We don't gate on `self._turns.binding.accepts(message)` here because an ACP session
        view already filters Core events to its own agent — the sweep just mirrors whatever
        the TurnBinding now reports for the bound agent."""
        self._turn_changed(self._turns.owner)

    def _turn_changed(self, owner: TurnOwner) -> None:
        self._strip.sweep(owner.busy)

    def close_activity(self) -> None:
        self.close_core_events()
