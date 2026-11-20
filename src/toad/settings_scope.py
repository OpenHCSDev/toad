"""The configuration state owned by an application or one viewed object."""
from abc import abstractmethod
from objectstate import ObjectState
from textual.dom import DOMNode

from toad.client.view_settings import ConversationSettingsOwner, SettingsReading, ViewSettingsOwner


class SettingsReader(SettingsReading, DOMNode):
    @property
    def configuration_scope(self) -> SettingsScope:
        return next((node for node in self.walk_ancestors(with_self=True)
                     if isinstance(node, SettingsScope)), self.app)


class SettingsScope(SettingsReader):
    @property
    @abstractmethod
    def configuration_state(self) -> ObjectState: ...

    def settings_widgets(self, widget_type):
        return self.walk_children(widget_type)


class ViewSettingsScope(ViewSettingsOwner, SettingsScope):
    """A file, thread or channel owns its display overrides."""

    @property
    @abstractmethod
    def configuration_panels(self): ...

    async def configuration_action_panels(self):
        """Backend configuration is absent unless the viewed object supplies targets."""
        return ()


class ConversationSettingsScope(ConversationSettingsOwner, ViewSettingsScope):
    """A thread or channel additionally owns conversation and composer settings."""



