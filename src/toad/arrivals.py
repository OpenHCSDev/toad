"""Unified viewport arrival animation shared by both frontends.

Every arriving item drawn in a viewport — bus message, tool call, thinking trace, CLI draft,
or live stream block — undergoes one simple animation (`ViewportArrival`) on the frontend's
shared `AnimationClock` along `FOLLOW_ARRIVAL`:

- Opacity rises (`0 -> 1`) in lockstep with translating upward into the viewport.
- Both short tail-following messages (`TailArrivalTarget`) and tall messages gliding up to
  their head (`HeadArrivalTarget`) use this same single transition, so tall messages glide
  smoothly in from the bottom edge instead of popping in and slowly fading motionless text.
- When viewport scroll travel is shorter than `arrival_slide_distance` (e.g. an empty or
  partially filled conversation), `ViewportArrivalState.offset_y` carries the remaining
  upward translation so every item entering the viewport slides and fades in together.
- `HeadReveal` shares `ArrivalTransition(TransitionTarget)` to glide a tapped message's head
  to the top of the viewport.

Plain mixin (`AnimatesArrivals`), no `ABC` metaclass and no toolkit imports, so both
Textual's `HistoryWindow` and Qt's `QtHistoryWindow` inherit it cleanly and supply
only their minimal geometry/paint hooks.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ui_theme.clock import AnimationClock
from ui_theme.effects import Mix, NEW_TEXT

from toad.client.fragments import HistoryFragment
from toad.client.reader_position import ArrivalTarget
from toad.motion import FOLLOW_ARRIVAL, HEAD_REVEAL, TransitionTarget


@dataclass(frozen=True, slots=True)
class ViewportArrivalState:
    """One frame of an item entering a viewport: its opacity (0..1) and vertical slide offset
    (distance below its resting position, shrinking to 0 as it lands)."""

    opacity: float = 1.0
    offset_y: float = 0.0
    active: bool = False

    def mix(self) -> Mix:
        return Mix(NEW_TEXT.start, NEW_TEXT.end, self.opacity)


SETTLED_ARRIVAL = ViewportArrivalState()


class ArrivalTransition(TransitionTarget):
    """One finite arrival or scroll transition owned by an `AnimatesArrivals` window."""

    owner: AnimatesArrivals

    @property
    def animation_visible(self) -> bool:
        return self.owner.arrival_animation_visible


class ViewportArrival(ArrivalTransition):
    """One unified arrival animation: items fade in (`0 -> 1`) as they translate upward into
    the viewport along `FOLLOW_ARRIVAL` on a single clock."""

    def __init__(
        self,
        owner: AnimatesArrivals,
        keys: tuple[object, ...],
        source_identities: Iterable[object] = (),
    ) -> None:
        self.owner = owner
        self.keys: tuple[object, ...] = keys
        self._key_set: frozenset[object] = frozenset(keys)
        self._source_identities: set[object] = set(source_identities)
        self.amount: float = 0.0
        self.target: ArrivalTarget | None = None
        self.scroll_start: float = 0.0
        self.scroll_at: float = 0.0
        self.scroll_travel: float = 0.0
        self.start_transition(owner.animation_clock, FOLLOW_ARRIVAL)

    def adopt_key(self, source_identity: object, key: object) -> bool:
        """Hand a still-running live arrival to its committed saved fragment at the exact
        current progress (`self.amount`), avoiding an opacity/offset snap mid-flight."""
        if source_identity not in self._source_identities:
            return False
        if key not in self._key_set:
            self.keys = (*self.keys, key)
            self._key_set = frozenset(self.keys)
        return True

    def attach_scroll(self, start: float, target: ArrivalTarget, destination: float) -> None:
        """Bind viewport scrolling to this arrival's clock so translation and fade finish together."""
        self.target = target
        self.scroll_start = start
        self.scroll_at = start
        self.scroll_travel = max(0.0, destination - start)

    def slide_distance(self, row_height: float) -> float:
        """Remaining upward slide when viewport scroll travel alone is shorter than the slide span."""
        span = self.owner.arrival_slide_distance
        if span <= 0.0:
            return 0.0
        desired = min(float(row_height), span) if row_height > 0.0 else span
        return max(0.0, desired - self.scroll_travel)

    def state(self, key: object, row_height: float = 0.0) -> ViewportArrivalState | None:
        if key not in self._key_set:
            return None
        slide = self.slide_distance(row_height)
        return ViewportArrivalState(
            opacity=self.amount,
            offset_y=(1.0 - self.amount) * slide,
            active=True,
        )

    def apply_amount(self, amount: float) -> None:
        self.amount = amount
        owner = self.owner
        target = self.target
        if target is not None:
            if not owner.follows_tail:
                self.detach_scroll()
            else:
                goal = target.goal(owner)
                self.scroll_travel = max(self.scroll_travel, goal - self.scroll_start)
                next_y = self.scroll_start + (goal - self.scroll_start) * amount
                self.scroll_at = target.step(owner, self.scroll_at, next_y)
                with owner.layout_scroll():
                    owner.scroll_y = self.scroll_at
        if self.keys:
            owner.repaint_arrival_keys(self.keys)

    def detach_scroll(self) -> None:
        self.target = None
        if self.owner.glide is self:
            self.owner.glide = None

    def land(self) -> None:
        owner = self.owner
        target = self.target
        self.target = None
        self.amount = 1.0
        if owner.glide is self:
            owner.glide = None
        owner.arrival_landed(self)
        if target is not None and owner.follows_tail:
            with owner.layout_scroll():
                target.land(owner)
            owner.refresh_visible_notifications()
        if self.keys:
            owner.repaint_arrival_keys(self.keys)

    def cancel(self) -> None:
        """Stop scrolling immediately (reader took over scrolling or jumped to latest)."""
        self.detach_scroll()
        if not self.keys:
            self.owner.arrival_landed(self)
            self.animation.stop()

    def stop(self) -> None:
        self.detach_scroll()
        self.owner.arrival_landed(self)
        self.animation.stop()


class HeadReveal(ArrivalTransition):
    """A message whose head sits above the viewport glides its head down into view at the
    top edge (`HEAD_REVEAL`). Layout insertions above it shift both endpoints; reader
    scrolling cancels it immediately."""

    def __init__(self, owner: AnimatesArrivals, start: float, target: float) -> None:
        self.owner = owner
        self.start = start
        self.target = target
        self.start_transition(owner.animation_clock, HEAD_REVEAL)

    def apply_amount(self, amount: float) -> None:
        self.owner.apply_head_reveal_scroll(self.start + (self.target - self.start) * amount)

    def land(self) -> None:
        owner = self.owner
        if owner.head_reveal is self:
            owner.head_reveal = None
            owner.apply_head_reveal_scroll(self.target)

    def shifted(self, rows: float) -> None:
        """Layout moved the reader `rows` mid-glide: keep gliding to the same message."""
        self.start += rows
        self.target += rows

    def cancel(self) -> None:
        """Stop where it is: the reader's own scrolling owns the rows now."""
        owner = self.owner
        if owner.head_reveal is self:
            owner.head_reveal = None
        self.animation.stop()


class AnimatesArrivals:
    """Shared semantic owner of unified viewport arrivals and head reveals.

    Listed before `ReaderPlacement` on both `HistoryWindow` (Textual) and
    `QtHistoryWindow` (Qt), so both frontends share one arrival state machine,
    one `ViewportArrivalState` interface, and one `gliding_to_end()` answer.
    """

    glide: ViewportArrival | None = None
    head_reveal: HeadReveal | None = None
    _arrived: tuple[object, ...] = ()
    _pending_arrival: ViewportArrival | None = None
    _applying_head_reveal: bool = False
    arrival_slide_distance: float = 0.0

    @property
    def arrivals(self) -> list[ViewportArrival]:
        """Active viewport arrivals for this window (lazy per-instance list)."""
        existing = self.__dict__.get("_arrivals")
        if existing is None:
            existing = []
            self.__dict__["_arrivals"] = existing
        return existing

    @property
    def live_seen_sources(self) -> set[object]:
        """Exact `source_identity` values already animated in as live blocks or drafts.

        When saved history commits those exact items they stay steady in place instead
        of double-animating, while any genuinely new bus message, tool call, or thinking
        trace arriving alongside an unrelated live block still slides and fades in cleanly.
        """
        existing = self.__dict__.get("_live_seen_sources")
        if existing is None:
            existing = set()
            self.__dict__["_live_seen_sources"] = existing
        return existing

    # ---- Backend hooks ----

    @property
    @abstractmethod
    def animation_clock(self) -> AnimationClock:
        """The frontend's shared `AnimationClock`."""

    @property
    @abstractmethod
    def arrival_animation_visible(self) -> bool:
        """Whether this window is alive and on screen so its animations may tick."""

    @abstractmethod
    def arrival_rows_height(self, keys: tuple[object, ...]) -> float | None:
        """Total laid-out height of the arrived rows in this window's scroll unit, or
        `None` when none of `keys` are laid out yet."""

    def prepare_arrival_layout(self) -> None:
        """Flush any deferred item layout before reading scroll geometry (Qt overrides)."""

    @abstractmethod
    def repaint_arrival_keys(self, keys: tuple[object, ...]) -> None:
        """Repaint only the rows/pages carrying `keys` after an arrival tick."""

    def follow_end(self) -> None:
        """Place the window at its followed tail (toolkits with a specialized jump override)."""
        self.scroll_y = self.tail_scroll_y

    histories: Iterable[object] = ()

    def refresh_visible_notifications(self) -> None:
        """Refresh delivery/read receipts for histories now visible in this window without
        re-arming source page reads (`history_pager.py` finish_source_work invariant)."""
        for history in tuple(self.histories):
            history.check_visible_notifications()

    def toolkit_animated_travel(self) -> float:
        """Remaining distance of any toolkit-owned scroll animation or fling."""
        return 0.0

    @property
    def animated_travel(self) -> float:
        """Remaining distance of a head reveal, else any toolkit-owned scroll travel."""
        if (travel := self.head_reveal_travel()) is not None:
            return travel
        return self.toolkit_animated_travel()

    def shift_toolkit_travel(self, rows: float, destination: float) -> None:
        """Shift any toolkit-owned scroll animation or fling by `rows` after layout moves."""

    def shift_travel(self, rows: float, destination: float) -> None:
        """Keep a head reveal and any toolkit-owned scroll travel aimed at the same rows."""
        self.shift_arrival_motion(rows)
        self.shift_toolkit_travel(rows, destination)

    # ---- Shared semantic operations ----

    def arrive_fragments(self, fragments: Sequence[HistoryFragment], *, live: bool = False) -> None:
        """One unified entry point for every arriving item: bus messages, tool calls,
        thinking traces, CLI drafts, and live blocks.

        When a live block (e.g. a fast tool call) commits to saved history while its live
        `ViewportArrival` is still in flight, that running arrival adopts the saved
        fragment's key at its exact current progress (`amount`) instead of snapping to
        `SETTLED_ARRIVAL` or re-gliding the viewport for an already-visible row."""
        if not (fragments and self.animation_clock.enabled and self.arrival_animation_visible):
            return
        seen = self.live_seen_sources
        if live:
            for fragment in fragments:
                seen.add(fragment.source_identity)
            keys = tuple(fragment.key for fragment in fragments)
            sources = tuple(fragment.source_identity for fragment in fragments)
            self.arrive(keys, glide_keys=keys, source_identities=sources)
            return
        active = self.__dict__.get("_arrivals") or ()
        fresh_keys: list[object] = []
        fresh_sources: list[object] = []
        for fragment in fragments:
            source = fragment.source_identity
            if any(arrival.adopt_key(source, fragment.key) for arrival in active):
                seen.discard(source)
                continue
            if source in seen:
                seen.discard(source)
                continue
            fresh_keys.append(fragment.key)
            fresh_sources.append(source)
        if fresh_keys:
            keys = tuple(fresh_keys)
            self.arrive(keys, glide_keys=keys, source_identities=tuple(fresh_sources))

    def clear_live_seen(self, sources: Iterable[object]) -> None:
        """Drop retired live-block identities once they leave the window."""
        seen = self.__dict__.get("_live_seen_sources")
        if seen:
            seen.difference_update(sources)

    def arrive(
        self,
        keys: tuple[object, ...],
        *,
        glide_keys: tuple[object, ...] | None = None,
        source_identities: Iterable[object] = (),
    ) -> None:
        """Animate `keys` into the viewport (synchronized upward translation + fade-in along
        `FOLLOW_ARRIVAL`) and glide a following reader smoothly to `glide_keys`."""
        if not self.animation_clock.enabled:
            return
        arrival: ViewportArrival | None = None
        if keys:
            arrival = ViewportArrival(self, keys, source_identities=source_identities)
            self.arrivals.append(arrival)
        moved = keys if glide_keys is None else glide_keys
        if moved and self.follows_tail:
            self._arrived += moved
            if arrival is not None:
                self._pending_arrival = arrival
            self.glide_to_end()

    def glide_to_end(self) -> bool:
        """Bind a unified scroll glide to the current arrival once `_arrived` is laid out.
        Works identically for short tail-following messages and tall head-placed messages."""
        if not self._arrived:
            return False
        height = self.arrival_rows_height(self._arrived)
        if height is None:
            return False
        self._arrived = ()
        pending = self._pending_arrival
        self._pending_arrival = None
        self.prepare_arrival_layout()
        target = self.reader_position.arrival_target(self)
        if target is None:
            return False
        destination = target.goal(self)
        start = min(max(0.0, self.tail_scroll_y - height), destination)
        previous = self.glide
        if previous is not None:
            previous.detach_scroll()
            start = min(destination, max(start, previous.scroll_at))
        with self.layout_scroll():
            self.scroll_y = start
            arrival = pending if pending is not None and pending in self.arrivals else ViewportArrival(self, ())
            arrival.attach_scroll(self.scroll_y, target, destination)
            self.glide = arrival
        return True

    def gliding_to_end(self) -> bool:
        """Whether an active arrival transition owns viewport scrolling."""
        if self._arrived and not self.glide_to_end():
            self._arrived = ()
            self._pending_arrival = None
        return self.glide is not None

    def stop_toolkit_scroll(self) -> None:
        """Stop any running toolkit scroll animation before `HeadReveal` takes over."""

    def start_head_reveal(self, target: float) -> bool:
        """Smoothly glide a message's head into view at `target` (`HEAD_REVEAL`), or jump
        immediately when animations are disabled."""
        self.cancel_head_reveal()
        self.stop_toolkit_scroll()
        destination = max(0.0, target)
        if not self.animation_clock.enabled:
            self.apply_head_reveal_scroll(destination)
            return True
        self.head_reveal = HeadReveal(self, self.scroll_y, destination)
        return True

    def apply_head_reveal_scroll(self, value: float) -> None:
        """Apply one `HeadReveal` step without tripping manual-scroll cancellation."""
        was = self._applying_head_reveal
        self._applying_head_reveal = True
        try:
            self.scroll_y = value
        finally:
            self._applying_head_reveal = was

    def head_reveal_travel(self) -> float | None:
        """Remaining scroll distance of an active `HeadReveal`, or `None` when idle."""
        return None if self.head_reveal is None else self.head_reveal.target - self.scroll_y

    def shift_arrival_motion(self, rows: float) -> None:
        """Keep an active `HeadReveal` aimed at the same message after layout shifts by `rows`."""
        if self.head_reveal is not None:
            self.head_reveal.shifted(rows)

    def cancel_head_reveal(self) -> None:
        if self.head_reveal is not None:
            self.head_reveal.cancel()

    def cancel_arrival_glide(self) -> None:
        if self.glide is not None:
            self.glide.cancel()
        self._arrived = ()
        self._pending_arrival = None

    def stop_arrival_motion(self) -> None:
        """Stop every active viewport arrival and head reveal (on unmount/destroy/park)."""
        self.cancel_head_reveal()
        self.cancel_arrival_glide()
        active = self.__dict__.get("_arrivals")
        if active:
            for arrival in tuple(active):
                arrival.stop()
            active.clear()

    def arrival_landed(self, arrival: ViewportArrival) -> None:
        if self._pending_arrival is arrival:
            self._pending_arrival = None
        active = self.__dict__.get("_arrivals")
        if active and arrival in active:
            active.remove(arrival)

    @property
    def has_active_arrivals(self) -> bool:
        """Whether any viewport arrival is currently animating (avoids lazy-allocating `_arrivals`)."""
        return bool(self.__dict__.get("_arrivals"))

    def has_arrival(self, key: object) -> bool:
        """Whether `key` is currently animating into the viewport."""
        active = self.__dict__.get("_arrivals")
        return bool(active) and any(key in arrival._key_set for arrival in active)

    def arrival_keys(self) -> frozenset[object]:
        """All keys currently animating into the viewport."""
        active = self.__dict__.get("_arrivals")
        if not active:
            return frozenset()
        return frozenset(key for arrival in active for key in arrival._key_set)

    def arrival_state(self, key: object, row_height: float = 0.0) -> ViewportArrivalState:
        """Current unified arrival state (`opacity`, `offset_y`, `active`) for `key`."""
        active = self.__dict__.get("_arrivals")
        if not active:
            return SETTLED_ARRIVAL
        for arrival in active:
            if (state := arrival.state(key, row_height)) is not None:
                return state
        return SETTLED_ARRIVAL

    def arrival_frame(self, key: object, row_position: float = 0.0) -> Mix | None:
        """Current fade `Mix` for `key`, or `None` when settled."""
        state = self.arrival_state(key)
        return state.mix() if state.active else None

    def arrival_opacity(self, key: object, row_position: float = 0.0) -> float | None:
        """Current opacity (0..1) for `key`, or `None` once settled."""
        state = self.arrival_state(key)
        return state.opacity if state.active else None
