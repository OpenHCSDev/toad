"""Toolkit-neutral owners for the Toad application lifecycle.

Behavior that both the Textual ``ToadApp`` and the Qt ``QtToadApp`` need in
identical form sits here, so the two apps inherit it instead of each writing
its own copy and drifting. Toolkit-coupled chrome (textual.App, QWidget)
stays on each app.
"""

from __future__ import annotations


class CorePrewarm:
    """Walk Core's local declaration catalog once before the first frame when this
    application's connection reads local bus files (`LocalCoreConnection.prewarm`).

    A remote connection (`RemoteCoreConnection`, e.g. Android) talks to Core over HTTPS and
    WebSocket and never loads local `RootFile` stores, so its `prewarm()` is a no-op —
    avoiding walking server-only modules (worker, team_heartbeat, nominal_census) that the
    APK neither needs nor ships.
    """

    def _prewarm_core_modules(self) -> None:
        self.coordination_access.connection.prewarm()
