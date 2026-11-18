"""The welcome's location line, for every frontend: the comms sidebar draws it under Toad's
banner while it holds the window (no tab shown)."""

from __future__ import annotations


class WelcomeLocation:
    """The location line: the attached agent's prefix, then where the window works.
    Textual's names the project it was started in; a remote client (Qt) names the bus
    connection it reads, its own launch directory saying nothing about that Core."""

    def location(self, app) -> str:
        raise NotImplementedError

    def location_line(self, app) -> str:
        return f"{app.agent_binding.welcome_prefix}{self.location(app)}"
