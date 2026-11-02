"""Compose native message dispatch with abstract capability declarations."""
from abc import ABCMeta

from textual.message_pump import _MessagePumpMeta


class NativeNodeMeta(_MessagePumpMeta, ABCMeta):
    """Keep both Textual dispatch and ABC requirements on the native node."""
