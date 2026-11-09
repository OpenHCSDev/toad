"""Command discovery needs the existing navigation and session capabilities."""

from toad.navigation_context import NavigationOwner
from toad.session_scope import SessionScope


class CommandTargetScope(NavigationOwner, SessionScope):
    """A navigating session whose identity supplies its command target."""
