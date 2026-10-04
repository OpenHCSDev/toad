# F3 folded into PR417

The explorer has one inspection state in `core/context_inspection.py`. Its route, revision, original inspection, native preview and unavailable reason belong to the state that can use them. `ContextExplorer` no longer stores `owner`, `wire_root`, `_inspection`, `_native` or `_observed_revision` as parallel lifecycle fields. The capture exporter and original installed App fixture use the same state.

## Existing owners and decisions

- `ContextInspection` still owns the registry/source observation, recorded manifests and authenticated source requests. Its `changed_since(previous)` compares the original recorded observations. The existing Core `ContextManifest.changed_since` remains the public segment-difference operation; this change does not replace that API with a boolean or duplicate a manifest family.
- `InspectionState` uses existing `DeclaredFamily`. Reading-owner states carry the route and, after an attempted read, its observed revision. Holding states carry the original inspection/revision; the native-readable member requires `NativeContextData`, and the unavailable member requires the actual error. No optional native/error pair, sentinel revision, additional wire DTO, store or codec is introduced.
- The state owns read acquisition/root admission, incoming observation acceptance, native source comparison, current contributor refresh, native success/failure, search roots/currentness and presentation groups. Same-source manifest refresh retains the acquired native object. Contributor refresh cannot replace a newer native object that completed during its await. A late response cannot acquire a detached or rebound state.
- Textual owns actual Worker cancellation and mounted recipient lifetime. The widget retains those fences and supplies rendering callbacks. On unmount its state detaches; subscription retirement remains in the existing `CoreEventReceiver` hook. `ContextSessionPanel` constructs a fresh explorer on restoration and retains only `ContextTreeIntent`.
- F3 does not change the 505 Tree resource retention, lazy disclosure, reader/cursor restoration or exact selected-observation checks. Native Tree nullable group/cursor inputs and the reader's optional selection remain framework/reader facts, not copies of inspection lifecycle.
- Recorded/source search borrows the selected node's original reader capability. It does not require a current native preview or substitute current text for a recorded request. The same source/selected/query fences cover error and result publication.

## Complete consumers

Production acquisition/presentation/search is confined to ContextInspection/its state family and ContextExplorer. MainScreen supplies identity through set_identity; ContextSessionPanel constructs the explorer with existing intent. The capture-state exporter and cold_context_installed_physical App contributor test were migrated, with no compatibility aliases. Before AST covers 288 Toad, 311 Core and 249 Textual modules with zero parse omissions. Lexical references do not prove dynamic MRO/callback resolution; those owners and handlers were read directly. After evidence covers the same production roots plus 393 test modules and 39 performance-tool modules, again with zero parse omissions. It finds no retired explorer lifecycle attribute consumer. The source sanity compiled those production modules and the four changed files in Python 3.14.7; it detects syntax errors, not installed import/App behavior.

The F3 production batch adds 299 lines and deletes 109. Across the full PR417 product delta against determining candidate 0b99, the two files add 478 and delete 138 lines.

## Actual strength and remaining work

This is a source checkpoint, not installed F3 or whole PR417 acceptance. Physical10 remains unchanged: exact recorded System /0 search, full read and matching clipboard passed; export failed because the original button was offscreen, and the distinct contributor step was not reached. The published native focus-next correction remains unrun.

The final batch must check state rebind/detach and native/contributor completion order in the affected App, then the same c603p01 recorded reader's export and exact distinct child. No menu/provider/fork/input repetition is required. The 485421 candidate is frozen and no package or capture loan is assumed. The prior full handback and all UNKNOWN/source/negative receipts remain preserved.

Channel deletion policy/forms/navigation belong to Sch's #621/#424. F3 changes no deletion semantics or SessionNavigation/Workspace methods. The only related behavior here is inspection retirement when its actual widget is unmounted.
