"""Two owners that raised on every use, each a toast on Tristan's screen (418 and 26 on 2026-11-04)."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from toad.conversation_kind import ChannelConversation
from toad.core.events import Subscription
from toad.resource_release import ResourceRelease
from toad.transcript_publication import SourcePublicationRequests


def test_channel_mentions_check_the_root_of_the_core_they_read() -> None:
    """A local snapshot of the shown page took the name of the Core it was asked about."""
    shown = object()
    roots, offered = [], []

    async def current_sidebar():
        return SimpleNamespace(require_snapshot=lambda: snapshot)

    async def run_thread(read, name):
        return read(name)

    async def source_is_current(source):
        return source is shown

    snapshot = SimpleNamespace(references=object(), mention_candidates=lambda name: (name,))
    conversation = SimpleNamespace(destination=lambda _references: SimpleNamespace(name="#comms"))
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
        query_one=lambda _kind: SimpleNamespace(set_mention_candidates=offered.append),
    )
    core = SimpleNamespace(root=Path("/core/root"))

    asyncio.run(ChannelConversation.update_mentions(view, core))

    assert roots == [Path("/core/root")]
    assert offered == [("#comms",)]


def test_a_deferred_publication_observes_with_a_callback_a_subscription_can_borrow() -> None:
    """A subscription holds its callback weakly, so a lambda raised and could not have lived anyway."""
    borrowed = []

    def observe(_view, _access, resume):
        borrowed.append(Subscription.weak_method(resume)())
        return ResourceRelease()

    work = SourcePublicationRequests(owner=None)
    view = SimpleNamespace(app=SimpleNamespace(coordination_access=None))
    work.defer(SimpleNamespace(binding=SimpleNamespace(view=view), thread_scope=SimpleNamespace(observe=observe)))

    assert borrowed == [work.thread_rows_changed]
