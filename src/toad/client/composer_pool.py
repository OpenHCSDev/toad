"""Shared semantic composer reuse pool owned by `WorkspaceViews` across both frontends.

Instead of constructing a brand-new composer subtree (editor, completion popups, queue
summary, delivery controls, info bar, shortcuts) for every open conversation tab, the
workspace keeps at most one live composer per semantic composer kind and rebinds it to
whichever tab is active, preserving each detached tab's lightweight `ComposerDraft`.

Both frontends inherit the exact same types:
- `PromptComposer` inherits `RebindableComposer` (so both Textual's `Prompt` and Qt's
  `Composer` own `pool_alive`, `capture_composer_draft`, and `rebind_conversation`).
- `QtConversation` (Qt) and `DeliveryFailureView` (Textual) both inherit
  `ComposerPoolHost` (sharing `on_composer`, `flush_composer_applies`, and
  `release_pooled_composer`).
- `WorkspaceViews` owns one `WorkspaceComposerPool` inherited by both
  `WorkspaceSessions` (Textual) and `QtWorkspaceViews` (Qt).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ComposerDraft:
    """Per-conversation composer state retained while its widget is lent to another tab."""

    text: str = ""
    cursor_offset: int = 0
    attached_files: tuple[object, ...] = ()
    takes_files: bool = True
    label: str = ""
    placeholder: str = ""
    read_only_reason: str = ""
    failure_text: str = ""
    mention_candidates: tuple[object, ...] = ()
    commands: tuple[object, ...] = ()
    dismissed_text: str = ""
    shell_mode: bool = False
    editor_state: object | None = None


class RebindableComposer:
    """A composer widget that can freeze its current tab's draft and rebind to another tab
    without reconstructing its widget tree."""

    def pool_alive(self) -> bool:
        """Whether this pooled composer's underlying native widget is still alive to reuse."""
        return True

    def capture_composer_draft(self) -> ComposerDraft:
        """Capture per-tab draft state and clear transient popups/subscriptions before detach."""
        return ComposerDraft()

    def rebind_conversation(self, host: ComposerPoolHost, draft: ComposerDraft) -> None:
        """Rebind this existing composer widget to `host` and restore `draft`."""


class ComposerPoolHost:
    """Shared mixin for conversation views whose composer may be deferred or lent to another
    active tab (`QtConversation` on Qt; `DeliveryFailureView` / `Conversation` on Textual)."""

    composer_placeholder: str = ""

    @property
    def _pending_composer_applies(self) -> dict[str, Callable[[Any], None]]:
        existing = self.__dict__.get("_composer_applies")
        if existing is None:
            existing = {}
            self.__dict__["_composer_applies"] = existing
        return existing

    @property
    def active_composer(self) -> Any | None:
        """The composer currently mounted in this view, or `None` while deferred or lent out."""
        return None

    def workspace_views(self) -> Any | None:
        """The workspace's `WorkspaceViews` owner, or `None` for a standalone view."""
        return None

    def workspace_composer_pool(self) -> WorkspaceComposerPool | None:
        """The workspace's shared composer pool, when this view belongs to a workspace."""
        views = self.workspace_views()
        return None if views is None else views.composer_pool

    def on_composer(self, kind: str, apply: Callable[[Any], None]) -> None:
        """Tell the composer something: now while this view holds it, else when it attaches,
        keeping only the latest of each `kind` (label, status, mentions, commands, queue)."""
        composer = self.active_composer
        if composer is not None:
            apply(composer)
        else:
            self._pending_composer_applies[kind] = apply

    def flush_composer_applies(self, composer: Any) -> None:
        """Replay every queued `on_composer` update onto `composer` once attached."""
        applies = self.__dict__.get("_composer_applies")
        if not applies:
            return
        queued = dict(applies)
        applies.clear()
        for apply in queued.values():
            apply(composer)

    def clear_composer_applies(self) -> None:
        """Discard queued updates when the view closes."""
        applies = self.__dict__.get("_composer_applies")
        if applies is not None:
            applies.clear()

    def release_pooled_composer(self, composer: RebindableComposer) -> ComposerDraft:
        """Detach `composer` from this view without destroying it and return its saved draft."""
        return composer.capture_composer_draft()


class WorkspaceComposerPool:
    """One reusable live composer per semantic composer kind, owned by `WorkspaceViews`."""

    def __init__(self) -> None:
        self._composers: dict[type, RebindableComposer] = {}
        self._holders: dict[type, ComposerPoolHost] = {}
        self._drafts: dict[ComposerPoolHost, ComposerDraft] = {}
        self.hits: int = 0
        self.misses: int = 0

    def has(self, kind: type) -> bool:
        """Whether a live pooled composer already exists for `kind`."""
        composer = self._composers.get(kind)
        if composer is None:
            return False
        if not composer.pool_alive():
            self._composers.pop(kind, None)
            self._holders.pop(kind, None)
            return False
        return True

    def current_holder(self, kind: type) -> ComposerPoolHost | None:
        return self._holders.get(kind)

    def saved_draft(self, host: ComposerPoolHost) -> ComposerDraft | None:
        return self._drafts.get(host)

    def register(self, kind: type, host: ComposerPoolHost, composer: RebindableComposer) -> None:
        """Record a freshly constructed composer in the pool under `kind`."""
        self._composers[kind] = composer
        self._holders[kind] = host
        self.misses += 1

    def acquire(
        self,
        kind: type,
        host: ComposerPoolHost,
        build: Callable[[], RebindableComposer],
    ) -> tuple[RebindableComposer, bool]:
        """Return `(composer, reused)` for `kind` bound to `host`.

        When a live composer of `kind` already exists in the pool, detach it from its
        previous holder (capturing that holder's `ComposerDraft`), rebind it to `host`
        with `host`'s saved draft, and return `(composer, True)` without rebuilding.
        """
        composer = self._composers.get(kind)
        if composer is not None and not composer.pool_alive():
            self._composers.pop(kind, None)
            self._holders.pop(kind, None)
            composer = None

        if composer is not None:
            previous = self._holders.get(kind)
            if previous is host:
                return composer, True
            if previous is not None:
                self._drafts[previous] = previous.release_pooled_composer(composer)
            draft = self._drafts.pop(host, ComposerDraft())
            self._holders[kind] = host
            composer.rebind_conversation(host, draft)
            self.hits += 1
            return composer, True

        composer = build()
        self._composers[kind] = composer
        self._holders[kind] = host
        self.misses += 1
        return composer, False

    def release(self, host: ComposerPoolHost, *, keep_draft: bool = False) -> None:
        """Detach every pooled composer currently held by `host` without destroying it."""
        held_kinds = [kind for kind, holder in self._holders.items() if holder is host]
        for kind in held_kinds:
            composer = self._composers.get(kind)
            self._holders.pop(kind, None)
            if composer is not None and composer.pool_alive():
                draft = host.release_pooled_composer(composer)
                if keep_draft:
                    self._drafts[host] = draft
            else:
                self._composers.pop(kind, None)
        if not keep_draft:
            self._drafts.pop(host, None)

    def release_matching(self, predicate: Callable[[ComposerPoolHost], bool], *, keep_draft: bool = False) -> None:
        """Release every pooled composer held by any host matching `predicate`."""
        matched = [holder for holder in set(self._holders.values()) if predicate(holder)]
        for holder in matched:
            self.release(holder, keep_draft=keep_draft)
        if not keep_draft:
            for host in [candidate for candidate in self._drafts if predicate(candidate)]:
                self._drafts.pop(host, None)

    def discard_all(self) -> None:
        """Drop every pooled reference on workspace shutdown."""
        self._composers.clear()
        self._holders.clear()
        self._drafts.clear()
