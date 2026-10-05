"""Source check: wrappers preserve declaration-owned MRO handler selection."""

from agent_comms.acp_extension import TranscriptSnapshotUpdate
from toad.core.events import AgentReady
from toad.widgets.conversation import Conversation, ConversationCommsConsumer
from sidebar_validation_driver import install_observer

# Resolution borrows the real nominal types; no event is delivered or App built.
conversation = object.__new__(Conversation)
consumer = ConversationCommsConsumer(conversation, None)
publications = ((conversation, AgentReady()),
                (consumer, object.__new__(TranscriptSnapshotUpdate)))
before = {type(event).__name__: tuple(handler.__name__ for handler in owner.handlers_for(event))
          for owner, event in publications}
install_observer()
after = {type(event).__name__: tuple(handler.__name__ for handler in owner.handlers_for(event))
         for owner, event in publications}
assert before == after, (before, after)
assert after == {"AgentReady": ("on_agent_ready",),
                 "TranscriptSnapshotUpdate": ("transcript_snapshot",)}, after
print("Observer preserves original MRO handler declarations (not delivery proof):", after)
