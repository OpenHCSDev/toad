"""What a click on a drawn link does, declared once for every frontend.

A link carries what it names (`LineLink`); the view that drew it opens it through one handler
per kind of link. The frontend supplies only how a target opens, how a recorded identity is
shown, how a file previews and how a warning reaches the reader.

A plain mixin, as `JumpsToLatest` is: Textual's widget metaclass refuses an `ABC` base and
Qt's shiboken metaclass clashes with one.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Callable, Iterable
from functools import partial
from pathlib import Path

from agent_comms.messaging.display_references import (
    ChannelDisplayReference,
    HistoricalDisplayReference,
    ThreadDisplayReference,
)
from metaclass_registry.mro_dispatch import MroDispatch, handles

from toad.client.fragments import FragmentToggle, HistoryFragment, Shown
from toad.client.line_blocks import LineLink, OpenHistoricalTarget, OpenReference, OpenTarget
from toad.client.message_file_links import MessageFileLink
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

    @handles(MessageFileLink)
    def open_message_file(self, link: MessageFileLink) -> None:
        self.run_link(partial(self.fetch_message_file, link))

    async def fetch_message_file(self, link: MessageFileLink) -> None:
        """Read the file from the bus its message is on, keep it, and open it; a refusal or a
        lost connection is told to the reader."""
        access = self.app.coordination_access
        try:
            path = await access.preparation.run_thread(
                lambda: link.fetched(access.observing(link.root).core))
        except (ValueError, OSError) as error:
            self.warn_link(f"{link.file.name} could not be read: {error}")
            return
        self.show_file(path)

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

    @abstractmethod
    def run_link(self, work: Callable[[], Awaitable[None]]) -> None:
        """Run a link's background work as this view's; its failure reaches the view's owner."""

    @abstractmethod
    def show_file(self, path: Path) -> None:
        """Open a file kept on this machine the way this frontend opens files."""


class TogglesFragmentShown(OpensLineLinks):
    """A history view whose drawn fragment disclosures toggle all parts sharing a source identity."""

    @abstractmethod
    def toggleable_fragments(self) -> Iterable[HistoryFragment]:
        """The drawn fragments this view can toggle."""

    @abstractmethod
    def apply_fragment_shown(
        self, target: HistoryFragment, changes: list[tuple[HistoryFragment, Shown]]
    ) -> None:
        """Apply toggled `Shown` states produced for `target`."""

    @handles(FragmentToggle)
    def toggle_fragment(self, link: FragmentToggle) -> None:
        """Toggle `link` across all drawn parts sharing its fragment's source identity."""
        fragments = self.toggleable_fragments()
        target = next((fragment for fragment in fragments if fragment.key == link.key), None)
        if target is None:
            return
        changes = [
            (fragment, link.toggled_shown(target.shown, fragment.shown))
            for fragment in fragments
            if fragment.source_identity == target.source_identity
        ]
        self.apply_fragment_shown(target, changes)
