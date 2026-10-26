"""Nominal widget families compose the registry and native widget lifetimes here."""
from agent_comms.declared_family import DeclaredFamily, FamilyMeta
from textual.widget import Widget


class DeclaredWidgetMeta(FamilyMeta, type(Widget)):
    """The shared public metaclass at the family/native-widget boundary."""


class DeclaredWidget(DeclaredFamily, Widget, metaclass=DeclaredWidgetMeta, affix="Widget"):
    """A widget family inherits registration and native message-pump behavior together."""
