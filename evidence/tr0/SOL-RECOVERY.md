# TR0 replacement recovery

Own worktrees: ~/wt/comms-tr0-sol-20260928 and ~/wt/toad-tr0-sol-20260928. Recovered committed predecessors e542fe82 and502ca75; retained-failures tree's entire uncommitted patch saved in predecessor-uncommitted.patch. Predecessor files unchanged. Core254 readiness published separately at7ab08688, now merged.

Closed retained failures in installed wheels:
- SessionView commits existing HistoryWindow follow intent before compositor paint and awaits visible document bodies for resumed navigation. Shared HistoryWindow uses inherited _scroll_to with release_anchor=False: Textual's public scroll_to omits that option from its inner call. Full original first-frame, deliberate scroll-up, concurrent page and snapshot assertions pass; removed the predecessor's unnecessary awaited resize/layout experiment.
- Relationship repaint measurement retains busy row geometry and stops only fixture spinner during unchanged-source measurement. Actual source-change assertions retained.
- Session sorting no longer borrows another process's turn lease. Existing real native loopback pilot now checks live sidebar busy authority despite UI-only idle metadata, compact row geometry at both widths and no provider-detail leakage. Sorting/Stopped behavior stays in sorting pilot.
- Removed e2e_pty's retired raw Pi stdout executor and its fabricated end-to-end driver; retained explicit-launch shared PTY fixture used by resize. Resize uses actual private native route and waits for real transcript readiness, not initial fixed sleep as proof.
- Real terminal pixel script needs Pillow/python-xlib; declared dev dependencies, no skips. MCP decision PTY and actual st/Xvfb pixel checks passed.

Evidence: sol-current-native-fixtures.log 3 passed27.22s; sol-collector-fixtures-current.log4 passed8.15s; sol-native-busy.log real installed ACP/native Pi/loopback1 passed34.89s. sol-terminal-current.log2 passed/resize startup failure; corrected readiness is being checked. Failed attempts retained, no claim of whole-suite green. Correct prepared native package for old core pin was native-current-689ce4b5d0592b9a; final source integration must keep current main's core/native/settings pins. No paid calls, live root/route/launcher changes or CI wait.
