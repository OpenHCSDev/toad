"""The configuration state owned by an application or one viewed object."""
from abc import abstractmethod
from objectstate import ObjectState
from textual.dom import DOMNode
from textual.widget import Widget


class SettingsReader(DOMNode):
    @property
    def configuration_scope(self) -> SettingsScope:
        return next((node for node in self.walk_ancestors(with_self=True)
                     if isinstance(node, SettingsScope)), self.app)

    @property
    def configuration_state(self) -> ObjectState:
        return self.configuration_scope.configuration_state

    @property
    def settings(self):
        return self.configuration_state.to_resolved_object()


class SettingsScope(SettingsReader):
    @property
    @abstractmethod
    def configuration_state(self) -> ObjectState: ...

    def settings_widgets(self, widget_type):
        return self.walk_children(widget_type)


class ViewSettingsScope(SettingsScope):
    """A file, thread or channel owns its display overrides."""


class ConversationSettingsScope(ViewSettingsScope):
    """A thread or channel additionally owns conversation and composer settings."""


class ObjectSidebarHost(Widget):
    """The native body in which a viewed object's properties are placed."""
