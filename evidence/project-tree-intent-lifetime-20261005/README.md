# Project panel reader intent lifetime

Base: actual Toad main75d249246612d7682fb0ead4a8e32fe5af9efba2. Einstein contributes this original family to Heisenberg's TC1 integration. Frozen Explorer953/107 and PR453 are unchanged.

## Original owner and concrete counterexample

ProjectTreeIntent retains filesystem identity, expanded paths, selected path and viewport. Native DirectoryTree owns disposable nodes, lazy line projection, filesystem loading and workers. RestorableProjectPanel._mount_tree retains its _intent while it awaits original restoration; ProjectSessionPanel.capture instead reads any newly admitted native tree directly. RetiringSidebar.retire_presentation captures before removing widgets. Retirement during restoration therefore replaces the intended selection/viewport with the unfinished native projection. This is a source-supported lifetime counterexample, not a measured runtime failure.

The planned repair makes the existing panel own capture during its complete restoration lifetime, migrates the session declaration's consumer, and preserves original canceled/unmounted worker custody. No second reader state, cache, native loader or readiness flag. Path changes and deferred native scroll must be read as part of the same family before editing. Exact shared-file claims are being coordinated directly with Heisenberg.

## Boundary decisions

Native TreeNode.data/cursor_node and Widget.parent are legitimately optional. Their source-bound API meanings remain intact. WorkspaceChrome owns fixed shared widgets and app placement; SidebarLayout owns order and gutters, the native parent owns child sorting, SidebarNavigation owns retained channel scroll/readiness and original frame release. No concrete duplicated authority was established in WorkspaceChrome, so no count-driven patch is proposed.

## Source evidence and acceptance

BEFORE.json reuses original audit.findings.Package/FunctionFacts:288 Toad production,396 tests,324 pinned Core and249 pinned Textual modules; zero parse omissions.125 lexical declaration/read/call sites are retained. Dynamic event/worker dispatch is read semantically, not claimed as AST behavioral proof. Pattern IDEN-3 applies to the competing interpretation of pending intent versus native projection; original optional boundaries are not violations.

Production and affected mounted App acceptance are pending. Tests come after coherent ownership repair. This source purpose grants no package/keeper/import/build/SDK/provider/input/recording access. It does not qualify the whole TC1 resource/cohort/continuous workspace journey.
