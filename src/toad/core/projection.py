"""Original nominal leaf projection, shared by context and native forms."""
from agent_comms.mro_dispatch import MroDispatch


class MroProjection(MroDispatch):
    """A leaf returns projection data rather than replacing its original value."""

    def consume_handlers_sync(self, value, handlers, *args, **kwargs):
        return next(iter(handlers))(value, *args, **kwargs)
