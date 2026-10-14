"""The mounted thread owns its loading surface before metadata admission."""

from toad.screens.main import MainScreen


class OpeningThreadScreen(MainScreen):
    def __init__(self, opening) -> None:
        super().__init__(opening.request.project,
                         opening.origin.source._agent or opening.navigator.app.agent_data,
                         agent_session_id=opening.request.target)
        self.initial_coordination_root = opening.request.root
        self._comms_thread = opening.request.target

    async def prepare_presentation(self) -> None:
        # The opening task admits resources, not workspace selection. Selecting
        # this shell must release the workspace frame hold before metadata I/O.
        if self._content_ready.is_set() and self._content_error is None:
            await super().prepare_presentation()

    async def finish_opening(self) -> None:
        await super().prepare_presentation()

    def opening_failed(self, error: Exception) -> None:
        self._content_error = error
        self._content_ready.set()
        if self.is_mounted:
            self.query_one("#session-opening").update(f"Thread unavailable: {error}")
