"""Android/Qt resync recovery, mid-scroll lazy loading, and jump-to-latest catch-up."""

from __future__ import annotations

import http.client
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_comms.acp_extension import TranscriptSnapshotUpdate
from agent_comms.coordination.errors import ReloadRequired, TranscriptChanged
from agent_comms.errors import RouteChangedError
from agent_comms.execution.transcript_sources import LatestPage, Through, UnreadTranscriptCursor
from agent_comms.presentation import NoRevision
from agent_comms.transcript.transcript_drafts import NoDraft
from agent_comms.transcript.transcripts import TranscriptPage
from agent_comms.transport.request import ConnectionDropped
from agent_comms.ui_model.observation import NotPublished, ObserverUnattached, Published
from agent_comms.ui_model.observation_wire import ObserverDied

from toad.client.application import ACTIVE_PRESENCE
from toad.client.committed_presentation import (
    CommitTranscript,
    FollowTailCommit,
    PreparedAppendCommit,
    PreparedPageCommit,
    RetainViewportCommit,
)
from toad.client.connection import (
    ClosedObservation,
    CoordinationAccess,
    FailedObservation,
    ObservationRetry,
    RemoteObserving,
    UnselectedRoute,
)
from toad.client.history_pager import (
    NEWER_END,
    OLDER_END,
    DirectionalPreparation,
    HistoryPager,
    MovingPreparation,
    PresentationBudget,
    Runway,
)
from toad.client.history_state import (
    LiveTranscript,
    RetiredSourceTranscript,
    UnreadTranscript,
    WorkingTranscript,
)
from toad.client.prepared_pages import PreparedPageSource, SavedHistory
from toad.client.resource_release import ResourceRelease
from toad.core.events import CoordinationObserved, CoreEventStream
from toad.history_jump import FollowsTail
from toad.transcript_publication import SourcePublicationRequests, TranscriptPublication


# --- Bug 1: Android background resume & transient-error recovery ---


@pytest.mark.asyncio
async def test_remote_resume_resets_backoff_recycles_sockets_and_replaces_observation():
    events_published: list[object] = []
    calls: list[str] = []

    class FakeRemoteConnection:
        def reset_connections(self) -> None:
            calls.append("reset_connections")

        def resume_current(self, access: CoordinationAccess):
            self.reset_connections()
            return access.observation.resumed_through(self, access)

        def observe(self, access: CoordinationAccess):
            calls.append("observe")
            fresh = RemoteObserving(
                sidebar=SimpleNamespace(),
                process=SimpleNamespace(),
                connection=self,
                served_root=Path("/bus"),
                access=access,
            )
            access.observation = fresh
            return fresh

    class FakePreparation:
        async def run_thread(self, fn, *args, **kwargs):
            return fn(*args, **kwargs)

    access = object.__new__(CoordinationAccess)
    access.connection = FakeRemoteConnection()
    access.retry = ObservationRetry()
    access.retry.lost(time.monotonic())
    access.retry.lost(time.monotonic())
    access.retry.lost(time.monotonic())
    assert access.retry.waiting(time.monotonic())
    access.opening = threading.RLock()
    access.preparation = FakePreparation()
    access.revision = NoRevision()
    access.route_task = None
    access.events = SimpleNamespace(publish=events_published.append)
    old_obs = RemoteObserving(
        sidebar=SimpleNamespace(),
        process=SimpleNamespace(),
        connection=access.connection,
        served_root=Path("/bus"),
        access=access,
    )
    access.observation = old_obs

    access.resume()
    assert not access.retry.waiting(time.monotonic())
    await access.route_task

    assert calls == ["reset_connections", "observe"]
    assert access.observation is not old_obs
    assert len(events_published) == 1 and isinstance(events_published[0], CoordinationObserved)


def test_focus_returned_clears_failed_backoff_and_ignores_closed():
    checked: list[str] = []
    access = object.__new__(CoordinationAccess)
    access.retry = ObservationRetry()
    access.retry.lost(time.monotonic())
    access.check_route = lambda: checked.append("check")  # type: ignore[method-assign]
    access.observation = FailedObservation(RuntimeError("offline"), UnselectedRoute(), access=access)

    access.focus_returned()
    assert not access.retry.waiting(time.monotonic())
    assert checked == ["check"]

    checked.clear()
    access.observation = ClosedObservation(access=access)
    access.focus_returned()
    assert checked == []


def test_application_presence_distinguishes_suspend_from_focus_loss():
    from PySide6.QtCore import Qt

    from toad.qt.window import PRESENCE_TRANSITIONS

    actions: list[str] = []
    app = SimpleNamespace(
        application=SimpleNamespace(backgrounded=lambda: actions.append("backgrounded")),
        coordination_access=SimpleNamespace(
            resume=lambda: actions.append("resume"),
            focus_returned=lambda: actions.append("focus_returned"),
        ),
        workspace_sessions=SimpleNamespace(
            selected=SimpleNamespace(reload=lambda: actions.append("reload"))
        ),
    )

    presence = ACTIVE_PRESENCE
    # Desktop focus loss -> focus_returned (does not tear down healthy socket)
    presence = PRESENCE_TRANSITIONS[Qt.ApplicationState.ApplicationInactive](presence, app)
    presence = PRESENCE_TRANSITIONS[Qt.ApplicationState.ApplicationActive](presence, app)
    assert actions == ["backgrounded", "focus_returned", "reload"]

    # Android suspend + transient inactive -> full resume (recycles sockets + fresh observation)
    actions.clear()
    presence = PRESENCE_TRANSITIONS[Qt.ApplicationState.ApplicationSuspended](presence, app)
    presence = PRESENCE_TRANSITIONS[Qt.ApplicationState.ApplicationInactive](presence, app)
    presence = PRESENCE_TRANSITIONS[Qt.ApplicationState.ApplicationActive](presence, app)
    assert actions == ["backgrounded", "resume", "reload"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        ConnectionDropped("wifi switched"),
        TimeoutError("socket timed out"),
        RouteChangedError("observation dropped"),
        http.client.RemoteDisconnected("closed"),
        ObserverDied("connector restarted"),
        ObserverUnattached("reattaching"),
    ],
)
async def test_working_transcript_defers_transient_transport_errors_instead_of_retiring_tab(error):
    deferred_callbacks: list[object] = []
    route_checks: list[str] = []
    failed_errors: list[Exception] = []

    class FakePageSource:
        def observe_availability(self, view, access, resume):
            deferred_callbacks.append(resume)
            return ResourceRelease()

    class FakeOwner:
        def __init__(self) -> None:
            self.page_source = FakePageSource()
            self.view = SimpleNamespace()
            self.window = SimpleNamespace(scroll_revision=0)
            self.app = SimpleNamespace(
                coordination_access=SimpleNamespace(
                    check_route=lambda: route_checks.append("check")
                )
            )
            self._source_observation = ResourceRelease()
            self._source_state = LiveTranscript()

        def paging_window(self):
            return ("through", None, ())

        def source_snapshot(self):
            return SimpleNamespace(current=lambda _owner: True)

        def finish_source_work(self, _state):
            self._source_state = LiveTranscript()

        def source_failed(self, err):
            failed_errors.append(err)
            self._source_state = RetiredSourceTranscript(LiveTranscript())

    owner = FakeOwner()
    op = WorkingTranscript(LiveTranscript(), owner)
    owner._source_state = op

    async def failing_work():
        raise error

    result = await op.execute(owner, failing_work)
    assert result is False
    assert failed_errors == []
    assert not isinstance(owner._source_state, RetiredSourceTranscript)
    assert len(deferred_callbacks) == 1
    assert route_checks == ["check"]


def test_source_publication_requests_wakes_on_coordination_observed():
    class Publisher:
        pass

    publisher = Publisher()
    events = CoreEventStream(publisher)
    resumed: list[str] = []

    class FakeView:
        is_attached = True

        def __init__(self) -> None:
            self.app = SimpleNamespace(coordination_access=SimpleNamespace(events=events))
            self._cb = None

        def _deliver(self, event, _sub) -> None:
            self._cb(event)

        def observe_core_callback(self, stream, event_type, callback):
            self._cb = callback
            return stream.subscribe(event_type, self._deliver)

        def retire_core(self, subscription) -> None:
            subscription.close()

        def start_publication(self, fn, *, exclusive: bool = False):
            resumed.append("started")
            return SimpleNamespace(is_finished=True, cancel=lambda: None)

    view = FakeView()
    requests = SourcePublicationRequests(owner=SimpleNamespace())
    publication = SimpleNamespace(
        binding=SimpleNamespace(view=view),
        thread_scope=SimpleNamespace(observe=lambda _v, _a, _cb: ResourceRelease()),
    )

    requests.defer(publication)
    assert resumed == []
    events.publish(CoordinationObserved(NoRevision()))
    assert resumed == ["started"]


# --- Bug 2: Mid-scroll lazy-loading jitter resilience & shared FollowsTail scroll ---


def test_moving_preparation_ignores_touch_jitter_but_flips_on_real_reversal():
    @dataclass
    class TouchWindow:
        presentation_budget: PresentationBudget = PresentationBudget(buffer_viewports=3)
        viewport_rows: int = 1600
        unfilled_rows: int = 0
        animated_travel: float = 0.0
        presenting: bool = True

        def runway(self, _history):
            return Runway(400, 4000)

    lookahead = DirectionalPreparation(TouchWindow())
    lookahead.position = 4000.0

    # User drags UP toward older messages.
    assert lookahead.observe(3600.0)
    assert isinstance(lookahead.demand, MovingPreparation)
    assert lookahead.demand.accepts_result(OLDER_END)

    # 12px capacitive finger jitter downwards during drag: must NOT flip or abort OLDER_END.
    assert lookahead.observe(3612.0)
    assert lookahead.demand.accepts_result(OLDER_END)
    assert lookahead.demand.read_rows(lookahead, None, OLDER_END, lookahead.window.runway(None)) > 0

    # Continued upward drag resets opposite jitter accumulator.
    assert lookahead.observe(3400.0)
    assert lookahead.demand.accepts_result(OLDER_END)

    # Sustained downward drag (> 5% of 1600px = 80px) DOES flip to NEWER_END.
    assert lookahead.observe(3520.0)
    assert lookahead.demand.accepts_result(NEWER_END)
    assert not lookahead.demand.accepts_result(OLDER_END)


def test_tui_wheel_reversal_flips_immediately_on_normal_3_row_step():
    @dataclass
    class TuiWindow:
        presentation_budget: PresentationBudget = PresentationBudget(buffer_viewports=3)
        viewport_rows: int = 20
        unfilled_rows: int = 0
        animated_travel: float = 0.0
        presenting: bool = True

        def runway(self, _history):
            return Runway(10, 100)

    lookahead = DirectionalPreparation(TuiWindow())
    lookahead.position = 100.0
    lookahead.observe(94.0)
    assert lookahead.demand.accepts_result(OLDER_END)

    # 3-row mouse wheel down (>= max(2.0, 20 * 0.05) == 2.0) flips immediately.
    lookahead.observe(97.0)
    assert lookahead.demand.accepts_result(NEWER_END)


def test_shared_follows_tail_records_scroll_revision_and_blocks_rejoin_when_newer_pages_exist():
    class DummyPosition:
        def __init__(self) -> None:
            self.deltas: list[float] = []

        def moved(self, _window, delta: float):
            self.deltas.append(delta)
            return self

        def joined_tail(self):
            return self

        def left_tail(self, _window):
            return self

    class DummyHistory:
        def __init__(self, has_newer: bool) -> None:
            self._has_newer = has_newer

        def has_more(self, end) -> bool:
            return self._has_newer and end is NEWER_END

    class DummyWindow(FollowsTail):
        def __init__(self, has_newer: bool) -> None:
            self._anchored = False
            self._restoring = False
            self.scroll_y = 100.0
            self.max_scroll_y = 100.0
            self.reader_position = DummyPosition()
            self.histories = {DummyHistory(has_newer)}

        @property
        def follows_tail(self) -> bool:
            return self._anchored

        def apply_anchor(self, anchor: bool) -> None:
            self._anchored = anchor

        def jump_to_latest(self) -> None:
            pass

    # At bottom of loaded rows, but newer pages exist -> must NOT rejoin tail; still bumps revision.
    win = DummyWindow(has_newer=True)
    win.record_reader_scroll(10.0)
    assert win.scroll_revision == 1
    assert win.follows_tail is False
    assert win.reader_position.deltas == [10.0]

    # When no newer pages remain -> rejoins tail cleanly (scroll + anchor both advance revision).
    win.histories = {DummyHistory(False)}
    win.record_reader_scroll(5.0)
    assert win.scroll_revision == 3
    assert win.follows_tail is True


# --- Bug 3: Stale unfocused tab jumps to latest instead of serial catch-up ---


@pytest.mark.asyncio
async def test_follow_tail_commit_jumps_to_latest_when_multi_page_gap_accumulated():
    positions_requested: list[object] = []

    class FakeLaterCursor:
        def later_page(self):
            return "after-old-watermark"

    class FakeSavedHistory(SavedHistory):
        def __init__(self) -> None:
            self.through = FakeLaterCursor()

    def make_snapshot(has_newer: bool, position):
        cursor = UnreadTranscriptCursor()
        page = TranscriptPage(
            events=(),
            before=cursor,
            after=cursor,
            has_older=True,
            has_newer=has_newer,
            snapshot=SimpleNamespace(position=position),
        )
        return TranscriptSnapshotUpdate(
            page=page,
            draft=NoDraft(),
            identity=SimpleNamespace(position=position, limit=Through(cursor)),
        )

    async def fake_read(*, position=LatestPage()):
        positions_requested.append(position)
        if isinstance(position, LatestPage):
            return make_snapshot(has_newer=False, position=position)
        return make_snapshot(has_newer=True, position=position)

    history = SimpleNamespace(page_source=FakeSavedHistory())
    window = SimpleNamespace(scroll_revision=1, follows_tail=True)

    # Following tail with multi-page gap -> upgrades from PreparedAppendCommit to PreparedPageCommit (LatestPage).
    plan = FollowTailCommit(window)
    result = await plan.read_snapshot(fake_read, history)
    assert len(positions_requested) == 2
    assert isinstance(positions_requested[1], LatestPage)
    assert plan.preparation is PreparedPageCommit
    assert not result.page.has_newer

    # Single-page gap (has_newer=False) -> stays on PreparedAppendCommit (1 read, no jump).
    positions_requested.clear()

    async def single_page_read(*, position=LatestPage()):
        positions_requested.append(position)
        return make_snapshot(has_newer=False, position=position)

    plan_single = FollowTailCommit(window)
    await plan_single.read_snapshot(single_page_read, history)
    assert len(positions_requested) == 1
    assert plan_single.preparation is PreparedAppendCommit

    # Retained viewport (scrolled up) -> never jumps to LatestPage.
    positions_requested.clear()
    retain = RetainViewportCommit()
    await retain.read_snapshot(fake_read, history)
    assert len(positions_requested) == 1


@pytest.mark.asyncio
async def test_history_pager_extend_skips_stale_intermediate_page_render_when_following_tail():
    actions: list[str] = []

    @dataclass(frozen=True)
    class FakePage:
        before: str
        after: str
        has_newer: bool

    class FakePager(HistoryPager):
        def __init__(self) -> None:
            self.page_source = SimpleNamespace(
                through="old",
                get=self._get,
                accept_page=self._accept,
            )
            self.pages = [
                SimpleNamespace(
                    prepared=SimpleNamespace(
                        page=FakePage(before="start", after="old", has_newer=False),
                        stop=10,
                        fragments=tuple(range(10)),
                    )
                )
            ]
            self._fake_window = SimpleNamespace(follows_tail=True)

        @property
        def window(self):
            return self._fake_window

        @property
        def drawn_end_more(self) -> bool:
            return False

        def source_snapshot(self):
            return SimpleNamespace(current=lambda _self: True)

        async def source_is_current(self, _snap) -> bool:
            return True

        async def _get(self, _req):
            actions.append("get_adjacent")
            return SimpleNamespace(
                fragments=("f1",),
                page=FakePage(before="old", after="mid", has_newer=True),
            )

        async def _accept(self, _self, _edge, _prepared) -> bool:
            return True

        def _update_edges(self) -> None:
            actions.append("update_edges")

        async def _load_page(self, _end, _current=lambda: True) -> bool:
            actions.append("load_intermediate_page")
            return True

        async def publish_held_latest(self, _current=lambda: True) -> bool:
            actions.append("publish_held_latest")
            return True

    pager = FakePager()
    assert await pager.extend("new") is True
    assert "load_intermediate_page" not in actions
    assert actions == ["get_adjacent", "update_edges", "publish_held_latest"]


# --- Bug 4: DM/thread view stale-witness, CoordinationObserved wakeup, and UnreadTranscript commit ---


def test_prepared_page_source_observe_availability_wakes_on_coordination_observed():
    class Publisher:
        pass

    events = CoreEventStream(Publisher())
    resumed: list[object] = []

    class FakeView:
        def __init__(self) -> None:
            self.thread_scope = SimpleNamespace(observe=lambda _v, _a, _cb: ResourceRelease())
            self._cb = None

        def _deliver(self, event, _sub) -> None:
            self._cb(event)

        def observe_core_callback(self, stream, event_type, callback):
            self._cb = callback
            return stream.subscribe(event_type, self._deliver)

        def retire_core(self, subscription) -> None:
            subscription.close()

    source = PreparedPageSource()
    access = SimpleNamespace(events=events)
    release = source.observe_availability(FakeView(), access, resumed.append)
    try:
        events.publish(CoordinationObserved(NoRevision()))
        assert len(resumed) == 1
    finally:
        release.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "resets_read", "checks_route"),
    [
        (ReloadRequired("witness gone"), True, False),
        (TranscriptChanged(), True, False),
        (ObserverDied("connector dropped"), False, True),
        (RouteChangedError("route switched"), False, True),
        (ConnectionDropped("socket reset"), False, True),
    ],
)
async def test_transcript_publication_resets_witness_on_reload_and_defers_transient_errors(
    error, resets_read, checks_route,
):
    deferred: list[object] = []
    route_checks: list[str] = []

    class FakePublication(TranscriptPublication):
        def current(self) -> bool:
            return True

        async def capture_application(self) -> bool:
            return True

        async def publish_applied(self) -> bool:
            raise error

    owner = SimpleNamespace(
        current_read=Published(SimpleNamespace()),
        source_requests=SimpleNamespace(defer=deferred.append),
    )
    binding = SimpleNamespace(
        view=SimpleNamespace(
            on_native_pump=lambda: False,
            live_blocks=(),
            turns=SimpleNamespace(owner=SimpleNamespace(captured_snapshot=lambda _blocks: None)),
            agent_binding=SimpleNamespace(committed_native_output=None),
            app=SimpleNamespace(
                coordination_access=SimpleNamespace(
                    check_route=lambda: route_checks.append("check"),
                )
            ),
        ),
        window=SimpleNamespace(reader_position=None),
        thread_scope=None,
    )
    pub = FakePublication(binding, owner, 0)

    assert await pub.publish() is False
    assert deferred == [pub]
    assert isinstance(owner.current_read, NotPublished) is resets_read
    assert bool(route_checks) is checks_route


@pytest.mark.asyncio
async def test_working_and_commit_transcript_publish_keeps_operation_active_until_finish():
    published_calls: list[str] = []
    painted_calls: list[object] = []

    class FakeOwner:
        def __init__(self) -> None:
            self.window = SimpleNamespace(scroll_revision=0)
            self.page_source = SimpleNamespace(through="cursor-1")
            self.view = SimpleNamespace(
                transcript=SimpleNamespace(
                    binding=SimpleNamespace(
                        painted=lambda _tr, cur: painted_calls.append(cur),
                    )
                )
            )
            self._source_state = UnreadTranscript()

        def paging_window(self):
            return ("through", None, ())

        def publish_committed(self) -> None:
            published_calls.append("publish_committed")
            self._source_state = self._source_state.publish()

    owner = FakeOwner()
    op = CommitTranscript(owner._source_state, owner, live_blocks=(), claims=())
    owner._source_state = op

    op.rows_published(owner)

    # The running operation stayed mounted in `_source_state` so `finish_source_work` still matches it,
    # while its wrapped state transitioned from UnreadTranscript to LiveTranscript ("Saved history available").
    assert owner._source_state is op
    assert isinstance(op.source, LiveTranscript)
    assert op.coverage.summary == "Saved history available"
    assert published_calls == ["publish_committed"]
    assert painted_calls == ["cursor-1"]
