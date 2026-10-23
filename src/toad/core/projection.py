"""Original nominal leaf projection, shared by context and native forms."""
from agent_comms.mro_dispatch import MroDispatch


class MroProjection[Result](MroDispatch):
    """A leaf returns projection data rather than replacing its original value."""

    def project(self, value, *args, **kwargs) -> Result:
        return next(self.handlers_for(value))(value, *args, **kwargs)
