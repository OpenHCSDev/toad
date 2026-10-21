"""Textual-facing: a historical-sessions screen reads handling notifications from the source it selected, and drops them when its body, screen or selection is gone."""

import asyncio

from agent_comms.comms import Comms
import pytest


@pytest.mark.parametrize("retirement", (None, "selection", "body", "screen", "detached"))
def test_historical_notification_keeps_selected_source_and_lifetime(
    tmp_path, monkeypatch, retirement,
):
    """Source callback boundary only; no mounted app."""
    from types import SimpleNamespace

    from agent_comms.historical_views import HistoricalThread, HistorySource
    from toad.screens.historical_sessions import HistoricalSessions
    from toad.widgets.wire_message_handling import WireMessageHandling

    old, live = Comms(tmp_path / "old"), Comms(tmp_path / "live")
    old.registry.declare(old.registry.new_thread("sender", frozenset(), str(tmp_path), created_at=10.0))
    old.registry.declare(old.registry.new_thread("agent", frozenset(), str(tmp_path), created_at=12.0))
    live.registry.declare(live.registry.new_thread("agent", frozenset(), str(tmp_path), created_at=212.0))
    old.messaging.initialize_private_initial_protocol()
    messages = (old.messaging.send("sender", "agent", "historical notification").message,)
    source = live.views.attach_history(old.root)
    item = HistoricalThread(source, source.provenance.require("agent"))
    published, errors, selected = [], [], []
    body = SimpleNamespace(
        is_attached=True, handling_references=(messages[0].reference,),
        show_notifications=published.append, show_notification_error=errors.append,
    )
    owner = SimpleNamespace(comms=live, _selection_generation=1, is_attached=True,
                            query_one=lambda *_: object())
    monkeypatch.setattr(WireMessageHandling, "within", lambda *_: (body,))
    unwrapped = HistorySource.notification_references

    def read(captured, archive, references):
        selected.append(captured.key)
        if retirement == "detached":
            live.bus.history.path.write_text("[]")
        result = unwrapped(captured, archive, references)
        if retirement == "selection":
            owner._selection_generation += 1
        elif retirement == "body":
            body.is_attached = False
        elif retirement == "screen":
            owner.is_attached = False
        return result

    monkeypatch.setattr(HistorySource, "notification_references", read)
    asyncio.run(HistoricalSessions.publish_handling(owner, item, 1))
    assert selected == [source.key]
    if retirement is None:
        assert not errors and len(published) == 1
        notification, = published[0][messages[0].seq, messages[0].message_id]
        assert notification.state == "Pending" and not notification.busy
    elif retirement == "detached":
        assert not published and len(errors) == 1
        assert "detached" in str(errors[0])
    else:
        assert not published and not errors
