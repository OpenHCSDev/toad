# T6 rendering ownership

Owner tree: /home/ts/wt/toad-t6-rendering-20260928, branch refactor/t6-rendering-20260928. Based on current Toad main df0a758. Predecessors and live installation untouched. Full authoritative scope: docs/refactor/T6-rendering.md and 00-RULES.md; owner defers CI and requires actual installed paths.

Shared kind checkpoint: import ConversationKind, ChannelConversation, DmConversation, IrcConversation from toad.conversation_kind. Consumers hold type[ConversationKind]. Decode boundary strings via ConversationKind.decode(name); derive the spelling via .declared_name. Family owns current/archive display identity, bounded page reads, route resolution and labels. HistoryKind and its behavioral switches are deleted. T5 retains sidebar/navigation implementation; its NavigationTarget only receives the mechanical shared-owner migration here. CommsChatView's string kind is derived from the typed owner, not stored twice.

Real installed-wheel kind-family test passes with a fresh actual Comms root and one newly declared kind; four actual-history reader cases pass (scope expansion, archive attach/detach, turn lease identity, cancellation/admission). The removed old fixture rewrote private bus bytes outside the owning log, violating current core's private-file/proof contract. Its initial failure remains in kind-history.txt; no internal raw-write fixture was ported as a new supported behavior.

PR110 audit consumed (23a6025): global workspace/chrome/controller lifetime work belongs to PR116. T6 does not duplicate it. Render preparation, task reuse, renderer protocol/backend/category ownership remain T6.

The reuse audit finds RenderPreparation in work_preparation.py reads task.reusable_result to control both content-addressed sharing and result retention; immutable capture tasks remain reusable, path-aware Markdown and ACP validation remain non-reusable. ReusableRenderTask will own its reusable input capture rather than a marker alone.

Remaining full T6 before acceptance: task-family/codec/reply transition/backends/categories and all callers; deletion guards; actual installed persistent/local rendering and UI pilots; before/after performance receipts. No full-surface completion claim at this checkpoint.
