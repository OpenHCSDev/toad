# Reconcile the roster before acquiring a pointer target

The existing installed control completed mixed thread/channel selection and pinning, then began another selection with SidebarObservation.pending true. Pinning changes native channel/member order. The next pointer gesture acquired a row coordinate without first reconciling that backend revision; Pilot owns press/release matching and correctly refuses to report a click when its recipients differ.

open_menu now calls the existing SidebarObservation.sync before scrolling and acquiring pointer geometry. select_rows uses that same owner after the menu is dismissed, before removing previous selected rows. No new wait loop, delay, queue, state mirror, production guard or renderer override was added. Every existing selection, backend action, visible-range and provider assertion is retained. This closes a concrete source ordering gap; the original failure did not record press/release hit geometry, so its sole cause remains unproved.

Package parsed 288 production,403 test,40 tool and249 native modules with no omissions. Only open_menu and select_rows changed; all124 assertions and every other declaration are equal. The changed source compiles without imports and diff check passes. The corrected installed journey has not run.

Batch09 stopped once at the native Ctrl-click check in select_rows, with the original operator joined after36.55seconds. The one three-package restoration passed; all1467 original nodes,953 assets and69 origins matched. The fresh privileged census reported no private references or gaps. Its whole return preserves91 raw references,51 files and two journals. The existing holder is independently closed. No retry or package rebuild occurred.

Original return: /home/ts/wt/toad-sidebar-selected-targets-20261006/.artifacts/selected-target-installed-20261006/485-batch09-installed-purpose/whole-handback.json
