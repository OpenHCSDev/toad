"""Qt widgets for the UX rows that frame the composer.

Mirror Textual's `PromptStack` siblings (`throbber_above`, `thread_activity`,
goal_bar + prompt): a thinking indicator line above the activity row, and a
session-status line showing the bound agent's model + any input-delivery
error. Both subscribe to the same shared owners Textual reads
(`ConversationTurn`, `agent_binding.model_info`, `DeliveryView`), so one
owner change updates both frontends without parallel state.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from pyqt_reactive.widgets.fitted_text import ElidedLine

from toad.agent_binding import NoAgentConnection
from toad.client.line_blocks import MutedRole
from toad.conversation_turn import ConversationTurn, TurnOwner
from toad.qt.lines import QtLineRenderer
from toad.qt.metrics import UiGap


class QtThinkingLine(QWidget):
    """One-row status line that mirrors Textual's `throbber_above`.

    Reads the host's `agent_binding.presentation.turns` via a shared
    `ConversationTurn`; its label describes whether a turn is in progress and
    what the agent is doing. Hidden when `turn.busy` is False so a quiet
    session doesn't paint a blank row.
    """

    def __init__(self, host, renderer: QtLineRenderer) -> None:
        super().__init__()
        self._host = host
        self._label = ElidedLine()
        self._label.setStyleSheet(renderer.color_style(MutedRole))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(UiGap.loose, UiGap.tight, UiGap.loose, UiGap.tight)
        layout.setSpacing(0)
        layout.addWidget(self._label, 1)
        self._turns = ConversationTurn(self._turn_changed, self._read_turns)
        self.hide()
        # Prime: a session that mounts into an already-busy agent still gets
        # the line painted, not just on the next turn change.
        try:
            self._turn_changed(self._turns.owner)
        except Exception:
            # Agent binding may not be ready during first paint; rely on the
            # subsequent `apply_bound_agent` / core-event refresh.
            pass

    def _read_turns(self):
        """Read the host agent's turn binding; a disconnected session has an
        idle `LocalTurnBinding(None)` via `NoAgentConnection.presentation`."""
        binding = getattr(self._host, "agent_binding", NoAgentConnection())
        return binding.presentation.turns

    def _turn_changed(self, owner: TurnOwner) -> None:
        """Refresh label from the current turn owner, OR fall back to the
        host's remote thread status for mailbox views where ``owner.busy`` is
        always False (``NoAgentConnection.presentation.turns`` is a dead
        ``LocalTurnBinding(None)``). The remote claude-a instance's thinking
        state lives on ``model.threads.rows[name].status.is_working()`` —
        same source the sidebar pulse animation reads."""
        if owner.busy:
            label = owner.describe() if hasattr(owner, "describe") else "Thinking…"
            self._label.setText(f"Thinking · {label}")
            self.show()
            return
        # Fallback: remote thread status for mailbox views.
        if self._remote_thread_is_working():
            self._label.setText("Thinking…")
            self.show()
            return
        self.hide()

    def _remote_thread_is_working(self) -> bool:
        """Read ``thread.status.is_working()`` for the host's thread from the
        app's threads model. Returns False if any lookup step fails — this is
        a best-effort surface, not a contract."""
        incarnation = getattr(self._host, "thread_incarnation", None)
        if incarnation is None:
            return False
        app = getattr(self._host, "app", None)
        if app is None:
            return False
        try:
            model = app.coordination_access.model()
            thread = model.threads.rows.get(incarnation.name)
            return thread is not None and thread.status.is_working()
        except Exception:
            return False

    def refresh(self) -> None:
        """Called by the host on agent-binding changes so the line follows the
        new binding without re-constructing the widget."""
        try:
            self._turn_changed(self._turns.owner)
        except Exception:
            self.hide()


class QtThreadStatusLine(QWidget):
    """Session-status row showing the bound agent's model info.

    Textual draws the same information via `OperationalSessionDetails` + title
    source. Qt reads it from `host.agent_binding.model_info(host.agent_title)`
    when the host has one; falls back to a plain thread-identity label so
    mailbox views (no agent binding) still show something meaningful.
    """

    def __init__(self, host, renderer: QtLineRenderer) -> None:
        super().__init__()
        self._host = host
        self._label = ElidedLine()
        self._label.setStyleSheet(renderer.color_style(MutedRole))
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(UiGap.loose, UiGap.tight, UiGap.loose, UiGap.tight)
        layout.setSpacing(0)
        layout.addWidget(self._label, 1)
        # Defer the first refresh: host.thread_identity + host.agent_binding
        # are typically bound AFTER the view's __init__ completes (via
        # `bind_thread` and the async identity resolution). Running refresh()
        # synchronously here reads an unbound identity and silently hides the
        # widget — the bug Tristan hit: "Mailbox: claude-a" visible in the
        # header but QtThreadStatusLine blank. Defer one event-loop tick so the
        # host's own init has landed.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.refresh)

    def refresh(self) -> None:
        """Refresh from the current agent binding + thread identity.

        Mailbox views carry `NoAgentConnection()` so `model_info` returns an
        empty / placeholder string; ACP views have a real `AgentConnection`
        whose `model_info(title)` names the model and token budget.
        """
        binding = getattr(self._host, "agent_binding", None)
        if binding is None or isinstance(binding, NoAgentConnection):
            # Mailbox view path: no bound agent, show thread-identity only.
            identity = getattr(self._host, "thread_identity", None)
            if identity is not None and hasattr(identity, "name"):
                self._label.setText(str(identity.name))
            else:
                self.hide()
                return
        else:
            try:
                title = getattr(self._host, "agent_title", "")
                info = binding.model_info(title)
                text = str(info) if info else ""
            except Exception:
                text = ""
            if not text:
                self.hide()
                return
            self._label.setText(text)
        self.show()
