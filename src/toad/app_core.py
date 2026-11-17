"""Toolkit-neutral owners for the Toad application lifecycle.

Behavior that both the Textual ``ToadApp`` and the Qt ``QtToadApp`` need in
identical form sits here, so the two apps inherit it instead of each writing
its own copy and drifting. Toolkit-coupled chrome (textual.App, QWidget)
stays on each app.
"""

from __future__ import annotations

from agent_comms.storage.locked_store import RootFile


class CorePrewarm:
    """Walk Core's declaration catalog once before the first frame.

    A cold tab's first wire revision and its first action menu each walk
    agent_comms and import every module of it (through
    ``RootFile.load_declarations`` and the lazy CLI registry). Those imports
    hold the GIL and the import lock against input, so they belong before the
    first frame rather than inside the first cold tab.
    """

    def _prewarm_core_modules(self) -> None:
        RootFile.load_declarations()
