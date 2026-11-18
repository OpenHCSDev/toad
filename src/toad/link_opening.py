"""What a click on a drawn link does, declared once for every frontend.

A link carries what it names (`LineLink`); the view that drew it opens it through one handler
per kind of link. The frontend supplies only how a target opens, how a recorded identity is
shown, how a file previews and how a warning reaches the reader.

A plain mixin, as `JumpsToLatest` is: Textual's widget metaclass refuses an `ABC` base and
Qt's shiboken metaclass clashes with one.
"""

from __future__ import annotations

from abc import abstractmethod

from agent_comms.messaging.display_references import (
    ChannelDisplayReference,
    HistoricalDisplayReference,
    ThreadDisplayReference,
)
from metaclass_registry.mro_dispatch import MroDispatch, handles

from toad.client.line_blocks import LineLink, OpenHistoricalTarget, OpenReference, OpenTarget
from toad.navigation_target import NavigationTarget
from toad.project_link import ProjectLink


class OpensLineLinks(MroDispatch):
    """A view whose drawn links open what they name: one handler per kind of link."""

    @handles(OpenTarget)
    def open_target(self, link: OpenTarget) -> None:
        self.select_target(NavigationTarget.named(link.target))

    @handles(OpenHistoricalTarget)
    def open_historical_target(self, link: OpenHistoricalTarget) -> None:
        self.select_historical(link.target, link.source)

    @handles(OpenReference)
    def open_reference(self, link: OpenReference) -> None:
        source = self.app.coordination_access.reference_context(link.reference.root)
        if not link.reference.current_in(source):
            self.warn_link(source.description or "This reference belongs to a replaced source.")
            return
        self.dispatch_sync(link.reference)

    @handles(ThreadDisplayReference, ChannelDisplayReference)
    def open_current_reference(self, reference) -> None:
        self.open_target(OpenTarget(reference.name))

    @handles(HistoricalDisplayReference)
    def open_recorded_reference(self, reference) -> None:
        self.open_historical_target(OpenHistoricalTarget(reference.name, reference.source))

    @handles(ProjectLink)
    def open_project_link(self, link: ProjectLink) -> None:
        self.preview_link(link)

    def open_link(self, href: str) -> None:
        """A drawn link hands its href back as a string; decode it once into the link it carries."""
        self.dispatch_sync(LineLink.from_href(href))

    # What the frontend supplies

    @abstractmethod
    def select_target(self, target: NavigationTarget) -> None:
        """Open this thread or channel, as its sidebar row does."""

    @abstractmethod
    def select_historical(self, name: str, source: str) -> None:
        """Show the identity an attached history recorded for `name`."""

    @abstractmethod
    def preview_link(self, link: ProjectLink) -> None:
        """Preview the file or open the address the link names."""

    @abstractmethod
    def warn_link(self, text: str) -> None:
        """Tell the reader why a link opened nothing."""
