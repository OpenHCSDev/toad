# Structural frame-pipeline investigation

Status: investigation in progress. The decision is which architectural boundary
to change next, based on ownership, invalidation and scaling evidence.

## Fixed baseline

- Toad main `43e57c91e9643cfab053630e1d5aaadd12cffad9`.
- Textual main `16ede007c34bec893b2dbedb3999223381129678`.
- Core `3996e820157b674f456974c1a8417de4776e1279`.
- CPython 3.14.2, normal GC policy; serial bounded fixtures, 4 GiB/no-swap caps.
- Existing final captures: `toad-pr108-landing-navigation` and
  `toad-pr108-landing-filters`. Their manifests carry source/runtime identities.
- Other active work owns recursive watcher startup (#109) and core/L0A migration
  (#107 and core #229). This investigation owns neither worktree nor deployment.

## Questions to resolve

1. Does a tab represent an entire retained application screen when only its
   conversation and thread-local state actually differ? Which global controls
   are still replicated, and how does their cost scale with tab count?
2. Which state changes invalidate geometry, text layout, paint, or source data?
   Are those ownership boundaries aligned, or does a small update fan out through
   unrelated ancestors and siblings?
3. Which phases publish geometry during a navigation/hydration transaction? How
   much work comes from explicit layout, resume/resize handling, queued timers,
   and geometry reads that synchronously rebuild derived maps?
4. How much of the cost is visible content, and how much is inactive widget/task/
   cache lifetime? Would a different representation remove work, or merely move
   it into cold activation?
5. Where does input acknowledgment sit relative to frame preparation and paint?
   Which delays are UI CPU, worker completion, GC, or terminal flush?

## Falsifiable hypotheses and controls

| Hypothesis | Structural evidence / probe |
| --- | --- |
| Global chrome is duplicated per screen | Ownership census and tab-count scaling with fixed source cohort |
| First-revisit preparation catches up duplicated controls | Measure tab reconciliation/mount counts separately; account for any work deliberately performed earlier |
| Reparenting invalidates too broad a scene | Native style/layout call counts, changed style rules, parent invalidation and geometry publication |
| Layout/hydration boundaries cause repeated work | Record causes and phase ordering, separating explicit navigation layout from subsequent callbacks |
| Retained history dominates the collector's live graph | Empty vs populated history with fixed viewport; active/inactive ownership census and ordinary GC observations |
| Rendering visible content is intrinsically dominant | Exclusive UI-thread spans and content/viewport scaling; separate collector pauses from render CPU |

Diagnostic counterfactuals must be labeled as such. Moving work earlier is not a
reduction in total work. Headless presentation is not native terminal latency.
Inclusive spans are not additive. GC trigger stacks are not heap ownership.

## Required decision output

- Source-backed ownership and update-flow map.
- Comparable probe receipts, including adverse outcomes and measurement overhead.
- Ranked architectural options, invariants and migration scope.
- A specific next change with a falsifiable acceptance boundary, plus evidence
  identifying tempting changes that would only improve a local minimum.
