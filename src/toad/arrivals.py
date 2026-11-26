"""Unified semantic arrival fades and scroll glides shared by both frontends.

Every arriving item — bus message, tool call, thinking trace, CLI draft, or live
stream block — flows through one coordinator (`AnimatesArrivals`) over the frontend's
shared `AnimationClock`:

- `ArrivalFadeRun`: fades a burst of newly arrived keys along `ARRIVAL` (`Cascade`),
  asking the window to repaint only those keys on each clock tick.
- `ArrivalGlide`: smoothly glides a tail-following reader down to arrived rows along
  `FOLLOW_ARRIVAL` instead of snapping in one frame.
- `HeadReveal`: smoothly glides a tapped/selected message's head up to the top of the
  viewport along `HEAD_REVEAL`, tracking layout shifts and cancelling on reader input.

Plain mixin (`AnimatesArrivals`), no `ABC` metaclass and no toolkit imports, so both
Textual's `HistoryWindow` and Qt's `QtHistoryWindow` inherit it cleanly and supply
only their minimal geometry/paint hooks.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterable, Sequence

from ui_theme.clock import AnimationClock
from ui_theme.effects import Mix

from toad.client.fragments import HistoryFragment
from toad.motion import ARRIVAL, FOLLOW_ARRIVAL, HEAD_REVEAL, TransitionTarget


class ArrivalFadeRun:
    """Keys that arrived together, rising row after row along `ARRIVAL` on the shared clock."""

    def __init__(self, owner: AnimatesArrivals, keys: tuple[object, ...]) -> None:
        self.owner = owner
        last = max(1, len(keys) - 1)
        self.positions: dict[object, float] = {key: index / last for index, key in enumerate(keys)}
        self.animation = owner.animation_clock.start(ARRIVAL, self)

    @property
    def animation_visible(self) -> bool:
        return self.owner.arrival_animation_visible

    def frame(self, key: object) -> Mix | None:
        position = self.positions.get(key)
        return None if position is None else self.animation.at(position)

    def opacity(self, key: object) -> float | None:
        mix = self.frame(key)
        return None if mix is None else mix.amount

    def stop(self) -> None:
        self.animation.stop()

    def repaint(self) -> None:
        owner = self.owner
        if self.animation.finished:
            owner.arrival_landed(self)
        owner.repaint_arrival_keys(tuple(self.positions))


class ArrivalGlide(TransitionTarget):
    """A reader following the end glides down to rows that arrived (`FOLLOW_ARRIVAL`)
    instead of jumping their height in one frame, landing on the end however far the rows
    grew meanwhile."""

    def __init__(self, owner: AnimatesArrivals, start: float) -> None:
        self.owner = owner
        self.start = start
        self.at = start
        self.start_transition(owner.animation_clock, FOLLOW_ARRIVAL)

    @property
    def animation_visible(self) -> bool:
        return self.owner.arrival_animation_visible

    def apply_amount(self, amount: float) -> None:
        owner = self.owner
        if not owner.follows_tail:
            self.cancel()
            return
        # Only ever down: a row that lands mid-glide moves the end, never the reader back up.
        self.at = max(self.at, owner.scroll_y, self.start + (owner.tail_scroll_y - self.start) * amount)
        with owner.layout_scroll():
            owner.scroll_y = self.at

    def land(self) -> None:
        owner = self.owner
        if owner.glide is self:
            owner.glide = None
        if owner.follows_tail:
            with owner.layout_scroll():
                owner.follow_end()

    def cancel(self) -> None:
        owner = self.owner
        if owner.glide is self:
            owner.glide = None
        self.animation.stop()


class HeadReveal(TransitionTarget):
    """A message whose head sits above the viewport glides its head down into view at the
    top edge (`HEAD_REVEAL`). Layout insertions above it shift both endpoints; reader
    scrolling cancels it immediately."""

    def __init__(self, owner: AnimatesArrivals, start: float, target: float) -> None:
        self.owner = owner
        self.start = start
        self.target = target
        self.start_transition(owner.animation_clock, HEAD_REVEAL)

    @property
    def animation_visible(self) -> bool:
        return self.owner.arrival_animation_visible

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
    """Shared semantic owner of arrival fades, tail-follow glides, and head reveals.

    Listed before `ReaderPlacement` on both `HistoryWindow` (Textual) and
    `QtHistoryWindow` (Qt), so both frontends share one arrival state machine and
    one `gliding_to_end()` answer.
    """

    glide: ArrivalGlide | None = None
    head_reveal: HeadReveal | None = None
    _arrived: tuple[object, ...] = ()
    _applying_head_reveal: bool = False

    @property
    def arrivals(self) -> list[ArrivalFadeRun]:
        """Active arrival fade bursts for this window (lazy per-instance list)."""
        existing = self.__dict__.get("_arrivals")
        if existing is None:
            existing = []
            self.__dict__["_arrivals"] = existing
        return existing

    @property
    def live_seen_sources(self) -> set[object]:
        """Exact `source_identity` values already faded in as live blocks or drafts.

        When saved history commits those exact items they stay steady in place instead
        of double-fading, while any genuinely new bus message, tool call, or thinking
        trace arriving alongside an unrelated live block still fades and glides cleanly.
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
        """Flush any deferred item layout before reading `tail_scroll_y` (Qt overrides)."""

    @abstractmethod
    def repaint_arrival_keys(self, keys: tuple[object, ...]) -> None:
        """Repaint only the rows/pages carrying `keys` after a fade tick."""

    def follow_end(self) -> None:
        """Place the window at its followed tail (toolkits with a specialized jump override)."""
        self.scroll_y = self.tail_scroll_y

    # ---- Shared semantic operations ----

    def arrive_fragments(self, fragments: Sequence[HistoryFragment], *, live: bool = False) -> None:
        """One unified entry point for every arriving item: bus messages, tool calls,
        thinking traces, CLI drafts, and live blocks."""
        if not (fragments and self.animation_clock.enabled and self.arrival_animation_visible):
            return
        keys = tuple(fragment.key for fragment in fragments)
        seen = self.live_seen_sources
        if live:
            for fragment in fragments:
                seen.add(fragment.source_identity)
            fade_keys = keys
        else:
            fade_keys = tuple(
                fragment.key for fragment in fragments if fragment.source_identity not in seen
            )
            for fragment in fragments:
                seen.discard(fragment.source_identity)
        self.arrive(fade_keys, glide_keys=keys)

    def clear_live_seen(self, sources: Iterable[object]) -> None:
        """Drop retired live-block identities once they leave the window."""
        seen = self.__dict__.get("_live_seen_sources")
        if seen:
            seen.difference_update(sources)

    def arrive(self, keys: tuple[object, ...], *, glide_keys: tuple[object, ...] | None = None) -> None:
        """Fade `keys` in row after row along `ARRIVAL`, and smoothly glide a tail-following
        reader down to `glide_keys` (defaulting to `keys`) along `FOLLOW_ARRIVAL`."""
        if not self.animation_clock.enabled:
            return
        if keys:
            self.arrivals.append(ArrivalFadeRun(self, keys))
        moved = keys if glide_keys is None else glide_keys
        if moved and self.follows_tail:
            self._arrived += moved
            self.glide_to_end()

    def glide_to_end(self) -> bool:
        """Glide to the end from where it stood before `_arrived` landed, once laid out.
        A running glide turns smoothly toward the new end from its current position."""
        if not self._arrived:
            return False
        height = self.arrival_rows_height(self._arrived)
        if height is None:
            return False
        self._arrived = ()
        self.prepare_arrival_layout()
        if not self.reader_position.joins_tail(self):
            # An arrival taller than the window is read from its head (`ArrivalPosition`).
            return False
        tail = self.tail_scroll_y
        start = max(0.0, tail - height)
        if self.glide is not None:
            self.glide.animation.stop()
            start = max(start, self.glide.at)
        with self.layout_scroll():
            self.scroll_y = min(start, tail)
            self.glide = ArrivalGlide(self, self.scroll_y)
        return True

    def gliding_to_end(self) -> bool:
        """Whether an active arrival glide owns the way to the tail."""
        if self._arrived and not self.glide_to_end():
            self._arrived = ()
        return self.glide is not None

    def start_head_reveal(self, target: float) -> bool:
        """Smoothly glide a message's head into view at `target` (`HEAD_REVEAL`), or jump
        immediately when animations are disabled."""
        self.cancel_head_reveal()
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

    def stop_arrival_motion(self) -> None:
        """Stop every active fade, arrival glide, and head reveal (on unmount/destroy/park)."""
        self.cancel_head_reveal()
        self.cancel_arrival_glide()
        active = self.__dict__.get("_arrivals")
        if active:
            for fade in tuple(active):
                fade.stop()
            active.clear()

    def arrival_landed(self, fade: ArrivalFadeRun) -> None:
        active = self.__dict__.get("_arrivals")
        if active and fade in active:
            active.remove(fade)

    def arrival_frame(self, key: object) -> Mix | None:
        """Current `ARRIVAL` cascade `Mix` for `key`, or `None` when settled."""
        active = self.__dict__.get("_arrivals")
        if not active:
            return None
        for fade in active:
            if (mix := fade.frame(key)) is not None:
                return mix
        return None

    def arrival_opacity(self, key: object) -> float | None:
        """How far the row `key` has risen (0..1), or `None` once settled."""
        mix = self.arrival_frame(key)
        return None if mix is None else mix.amount
