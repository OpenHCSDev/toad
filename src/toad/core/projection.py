"""Original nominal leaf projection, shared by context and native forms."""
from metaclass_registry.mro_dispatch import MroDispatch


class MroProjection[Result](MroDispatch):
    """A leaf returns projection data rather than replacing its original value."""

    def project_value(self, value, *args, **kwargs) -> Result:
        return next(self.handlers_for(value))(value, *args, **kwargs)
