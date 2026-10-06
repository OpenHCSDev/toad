# Sidebar responsiveness and independent native frame publication

## Changes

- Sidebar visibility uses its existing displayed ancestry. Parked tabs retain intent and apply geometry on activation, without restyling or hydrating on every toggle.
- Deleted the pointer-only descendant refresh walk and old conversation sidebar-padding subscriber. SidebarLayout owns placement; native invalidation owns paint.
- Context projection preparation runs in the original worker. Native Tree reconciliation preserves the acquired reader without deep whole-inspection comparisons or repeated descendant walks.
- WorkspaceScreen supplies original mutation/deferred roots to Textual72. Native Screen/Compositor owns geometry, damage and callback admission; there is no frontend region mask or whole-frame timer veto.
- FramePresentation joins the original writer with its canonical scene identity. Old writer completions cannot release callbacks into a different selected scene.
- SidebarNavigation consumes native publication and actual scroll restoration; its duplicate private layout calls are deleted.

The candidate pins native e15d066a6 in the manifest and lock. Parent integration478 and accepted helper repairs483/484 are included by normal merge. Historical wheels, frozen operator roots and saved journals remain unchanged.

## Verified

Complete original Package source parse:728 Toad modules,710 native modules, zero omissions. Changed source compiles and diff check passes. Existing context annotation checks verify acquired-model rebind and reader remount.

Matched headless source App, ten logical tabs: actual visible right sidebar median50.4ms/p9558.5ms/max112.9ms; left median54.5ms/p9571.6ms/max185.5ms; empty stderr. The old429/424ms figures selected a hidden zero-size sidebar and are invalid visible-toggle measurements, not a speedup baseline.

Matched held-body App passed7.55s with empty stderr: real delayed child Unmount, two chained writers, available Conversation input pump, native MouseDown protection/replacement, strict held cut-cell exclusion and retained damage under a translucent modal, editor draft and collapse/reentry. The original control now requests a native repaint rather than asserting damage retention after invoking a clean compositor. Guards are unchanged. No SDK/provider/public input ran.

Native owner separately verified17 publication controls and12 changed callback/inline/translucent/hit/reparent controls. The earlier225c callback hang and all original App/control negatives are retained.

## Remaining

These are actual source App/native results, not installed or physical-terminal readiness. Coherent candidate packaging, staged saved-history/sidebar/wheel-scroll recording and the local installation remain to be completed. No smooth-scrolling claim is made from these headless timings.

Source/consumer evidence: evidence/sidebar-responsiveness-20261006/SOURCE-CHECKPOINT.md.
