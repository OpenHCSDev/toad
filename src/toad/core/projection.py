"""Original nominal leaf projection, shared by context and native forms."""
from metaclass_registry.mro_dispatch import MroDispatch


class MroProjection[Result](MroDispatch):
    """A leaf returns projection data rather than replacing its original value."""

    def project_value(self, value, *args, **kwargs) -> Result:
        for handler in self.handlers_for(value):
            return handler(value, *args, **kwargs)
        # A missing handler is a declaration gap; StopIteration would vanish inside a caller's generator.
        raise TypeError(f"{type(self).__name__} declares no projection for {type(value).__name__}")
