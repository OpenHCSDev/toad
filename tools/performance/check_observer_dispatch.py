"""Verify instrumentation preserves Textual's decorated-handler dispatch count."""

from toad.acp.messages import TranscriptSnapshot
from toad.agent import AgentReady
from toad.widgets.conversation import Conversation
from sidebar_validation_driver import install_observer

conversation = object.__new__(Conversation)
messages = (TranscriptSnapshot((), None), AgentReady())
before = {type(message).__name__: len(list(conversation._get_dispatch_methods(message.handler_name, message)))
          for message in messages}
install_observer()
after = {type(message).__name__: len(list(conversation._get_dispatch_methods(message.handler_name, message)))
         for message in messages}
assert before == after, (before, after)
assert all(count == 1 for count in after.values()), after
print("Observer retains exactly one dispatch per decorated transcript/ready message:", after)
