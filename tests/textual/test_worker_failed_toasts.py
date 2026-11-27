"""Two owners that raised on every use, each a toast on Tristan's screen (418 and 26 on 2026-11-04)."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from agent_comms.messaging.channel_targets import ChannelTarget

from toad.client.conversation_capabilities import ConversationActivity
from toad.client.conversation import ChannelConversation
from formbridge.publications import Subscription
from toad.client.resource_release import ResourceRelease
from toad.transcript_publication import SourcePublicationRequests
from toad.widgets.comms_chat import CommsChatView


def test_channel_mentions_check_the_root_of_the_core_they_read() -> None:
    """A local snapshot of the shown page took the name of the Core it was asked about."""
    shown = object()
    roots, offered = [], []

    async def current_sidebar():
        return SimpleNamespace(require_snapshot=lambda: snapshot)

    async def run_thread(read, argument):
        return read(argument)

    async def source_is_current(source):
        return source is shown

    snapshot = SimpleNamespace(references=object(), mention_candidates=lambda name: (name,))
    conversation = ChannelConversation(ChannelTarget("#comms"))
    view = SimpleNamespace(
        message_history=SimpleNamespace(source_snapshot=lambda: shown, source_is_current=source_is_current),
        conversation=conversation,
        app=SimpleNamespace(
            coordination_access=SimpleNamespace(
                current_sidebar=current_sidebar,
                observation=SimpleNamespace(observes=lambda root: roots.append(root) or True),
            ),
            preparation=SimpleNamespace(run_thread=run_thread),
        ),
        show_mention_candidates=offered.append,
    )
    core = SimpleNamespace(root=Path("/core/root"))

    # The sequence is the shared owner's; a frontend's view only shows what it read.
    assert CommsChatView.update_channel_mentions is ConversationActivity.update_channel_mentions
    asyncio.run(ConversationActivity.update_channel_mentions(view, core))

    assert roots == [Path("/core/root")]
    assert offered == [("#comms",)]


def test_a_deferred_publication_observes_with_a_callback_a_subscription_can_borrow() -> None:
    """A subscription holds its callback weakly, so a lambda raised and could not have lived anyway."""
    borrowed = []

    def observe(_view, _access, resume):
        borrowed.append(Subscription.weak_method(resume)())
        return ResourceRelease()

    work = SourcePublicationRequests(owner=None)
    view = SimpleNamespace(
        app=SimpleNamespace(coordination_access=SimpleNamespace(events=SimpleNamespace())),
        retire_core=lambda _sub: None,
        observe_core_callback=lambda _events, _kind, _cb: object(),
    )
    work.defer(SimpleNamespace(binding=SimpleNamespace(view=view), thread_scope=SimpleNamespace(observe=observe)))

    assert borrowed == [work.thread_rows_changed]
