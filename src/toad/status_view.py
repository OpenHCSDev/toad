"""Conversation status and feedback, separate from observed thread activity."""

from rich.text import Text as RichText
from textual import getters
from textual.content import Content
from textual.reactive import var
from textual.widget import Widget

from toad.app_node import ToadNode
from toad.widgets.flash import Flash


class StatusView(ToadNode, Widget):
    """The actual status field and flash widget consumed by connection operations."""

    feedback = getters.query_one(Flash)
    thread_status: var[str | Content | RichText] = var("")
