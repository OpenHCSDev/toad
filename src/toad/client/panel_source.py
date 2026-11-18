"""A thread pane panel's read of the observation serving its thread's root.

The Comms and Context panels read Core through the observation that serves their
thread's root. While Core cannot be read (the connector restarting, an unreachable
remote), the current observation is a failed one, and asking it for the source raises
the failure that stopped it. A panel shows that failure as the sidebar shows it
(`SidebarStatusLine.unavailable_text`) and reads again on its next refresh, rather than
ending its refresh with the error unhandled. Textual's `ThreadCommsSidebar` and
`ContextExplorer`, and Qt's `QtThreadCommsPanel` and `QtContextExplorer`, inherit this
through their shared panel owners.
"""

from __future__ import annotations

from agent_comms.cli_support.cli_failures import CLI_FAILURES

from toad.client.sidebar_lines import SidebarStatusLine


class PanelSource:
    """A plain parent: each frontend's panel says where the unavailable text shows."""

    async def observed_source(self, access, preparation, root):
        """The observation serving ``root``, or None once the panel has said why Core
        cannot be read now."""
        try:
            return await preparation.run_thread(lambda: access.observing(root))
        except CLI_FAILURES as error:
            self.show_source_unavailable(SidebarStatusLine.unavailable_text(error))
            return None

    def show_source_unavailable(self, text: str) -> None:
        """Say in the panel why its source cannot be read."""
        raise NotImplementedError
