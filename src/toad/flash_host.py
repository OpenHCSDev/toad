"""Transient status flash contract: text shown briefly to the user when an action
completes, succeeds or errors. Textual draws through a `widgets.flash.Flash`
feedback block; Qt dispatches through the window's `status_line`. Both `Conversation`
views bind this contract so callers can flash without knowing the backend.

Plain class (not ABC) so toolkit metaclasses can co-exist in the MRO.
"""


class FlashHost:
    """A view that can flash a transient status message. Subclasses own how the
    text is drawn and how long it stays; callers only supply the text."""

    def flash(self, text: str) -> None:
        """Flash a neutral status message."""
        raise NotImplementedError

    def flash_success(self, text: str) -> None:
        """Flash a success-styled status message."""
        raise NotImplementedError

    def flash_error(self, text: str) -> None:
        """Flash an error-styled status message."""
        raise NotImplementedError
