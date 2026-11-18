"""Pages listed together and shown one at a time, each built the first time it is shown.

A sidebar panel menu lists one page per setting of the viewed object, and the settings
screen lists one page per declared section; one page is shown at a time. Building every
listed page up front cost each opened tab every form (about four seconds at a phone's
speed) and held the settings screen's first frame behind every page's form. Both inherit
this rule; a frontend that keeps every page mounted (Textual's settings switcher) shows,
and so builds, each of them."""

from __future__ import annotations

from abc import abstractmethod


class LazyPages[Key, Page]:
    """A page for each listed key, built the first time it is asked for and kept after."""

    pages: dict
    """Each shown key's page, kept while another is shown."""

    @abstractmethod
    def realize_page(self, key: Key) -> Page:
        """Build this key's page."""

    def page(self, key: Key) -> Page:
        """This key's page, built the first time it is shown and never when it is only listed."""
        if key not in self.pages:
            self.pages[key] = self.realize_page(key)
        return self.pages[key]
