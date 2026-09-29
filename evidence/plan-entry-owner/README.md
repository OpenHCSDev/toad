# T4 ACP Plan leaf completion

Ready source **5d74ef69** on current main **c2534676** (merged149/150), PR151.
Own persistent tree: ~/wt/toad-plan-entry-owner-sol-20260928. Parent merges and
installs. Tesla142 owns operational source/workspace custody; Carver owns process
lifetime/urgent framework fixes. Their exact shared-file boundaries were read and
coordinated before editing; no other agent's tree or live state was changed.

## Deletion and ownership

**191 product lines deleted, 142 added.** Tests: **3 deleted, 254 added**. The new
physical ACP family pilot and installed extension/deletion guard protect a path
that lacked this coverage and found a real malformed-input acceptance bug.

Deleted nested Plan.Entry/update_status, status-string rendering/completion
switches, both UI raw entry decoders, duplicate completion mutation, unused
priority roster/import/CSS, the dead PlanApp demo and unused Prompt.plan.
All actual source and retained sidebar-pilot callers migrate together. Main and
Conversation consume the same typed list directly; no old alias survives.

PlanStatus is the shared DeclaredFamily public ABC. Cases own marker/completion
behavior; grid composition is inherited from the parent. PlanItem owns admitted
Content, opaque external priority metadata and the typed status. Its ACP factory
binds guaranteed fields by declaration, once at admission. Presentation does not
rewrite or validate external metadata. No secondary roster, renderer, store,
codec subclass or compatibility path. State is transient UI presentation;
no durable/runtime storage format or cutover tool changed.

New-case experiment: one ReviewingPlanStatus declaration, zero widget/root/
decoder roster edits, proved through installed normal App and cropped text.
External ACP membership remains the official SDK's contract; this does not
claim arbitrary new status names are accepted on an unchanged external protocol.

## Real bug and boundary correction

The physical negative wire case exposed SDK Plan._skip_invalid_items_0:
SessionNotification(strict=True) silently skips malformed rows, then the prior
boundary returned their untouched raw payload. A numeric content reached the
renderer, while missing/unknown fields escaped notification validation.
NotificationItems uses existing MroDispatch on the SDK AgentPlanUpdate class and
strict TypeAdapter(list[SDK PlanEntry]) in the existing ordered validation worker.
The SDK still owns the external field declaration. Unknown extensions remain
untouched, and no SDK graph is imported by normal UI startup. The actual physical
malformed-status/missing-priority/wrong-type test now shows three rejection notes
and preserves the last valid plan. No per-use type guards were added.

Computed completion initially changed its value without toggling the native CSS
class. The Plan watcher now projects that derived value through Textual's public
set_class; all_complete has one derived authority. Real paint/animation acceptance
proved this correction, including completion after an empty plan.

Latest authoritative22:16 NRA/refactor-audit skills, pattern README/full relevant
files and chain_terms.py were reread and applied. IDs: IMPL-1/4/5, BOUND-1/2,
MEMB-1, TIME-6/9, AGENT-8. Dominant chain kinds were reviewed; no fabricated
one-rule-per-boolean machinery. SDK is external, not an internal format adapter.

## Executed acceptance

Noneditable installed Toad wheel from this exact product source; core322
8ad034a60d91b0bcb8e90bbeca326e01d2dfb7cc and Textual8
c9743801c98dc570f82f82e25915ecce89800f4b, matching current main dependency pins.
See installed-origins.json for actual imports, package provenance and resolved
public annotations. Parent owns the newer paired live installation.

- `TMPDIR=$PWD/.artifacts/pytest-plan timeout 70 .venv/bin/python tests/plan_status_installed_pilot.py`
  **exit0**, installed-wire-accepted.log. Normal installed App starts a physical
  official-SDK ACP peer via AgentProcess; initialize/newSession/prompt, ordered
  validation worker, event bubbling, reactive composition and compositor are
  actual implementations. All SDK status markers and conversation/sidebar text
  paint; consecutive updates reuse one Plan, newly-completed rows animate,
  already-completed rows are static, animation stops its timer, resize paints,
  empty reset and optional-sidebar retirement/prepare/reveal work. Three raw
  malformed physical notifications are visibly rejected. No provider/model,
  patched transport, intercepted messages or fake UI scene.
- Installed guard batch **2 passed in2.81s**: actual new-case paint plus permanent
  deletion guard. installed-guards-final.log. Environment fixtures only;
  no mocked source/render/transport or private-cache goldens.
- Existing external SDK contract helper **exit0**: other update shapes retain raw
  extension-bearing identity and malformed input rejection. sdk-contract-final.log.
  Only the direct contract helper ran; its intercepted-message pilot was not used.

Earlier red logs are retained. First/fourth were pre-frame paint timing, second
found completion CSS, third omitted the existing sidebar prepare hook, fifth
found real SDK malformed-row acceptance. Assertions were fixed or lifecycle
setup corrected without removing any requested behavior. Final gates above pass;
no broad suite, live Pi provider or native-equivalence claim is made.

## Structural evidence and limits

Shared independent ratchet: **zero positive existing deltas**. Plan131→66,
Conversation2159→2150, MainScreen482→475, Prompt469→468 AST spans; ACP Agent1311
unchanged. Deleted classes remain deleted; new owner measurements have no baseline.
Census: every touched file has non-increasing chain terms; aggregate terms0,
string-key subscripts-2, literal gets-4, string equality-8, codec subclasses0.
All product ASTs parse in the permanent guard. ratchet-final.json/census-final.json.
The initial raw-field implementation added one string subscript (ratchet-first.json).
Guaranteed fields now bind through their owning input signatures, removing raw
projections rather than changing bracket reads to get calls; final delta is-2.

Full raw NRA source/dependency context snapshots, no automatic context omission,
single bounded worker, no cache: base723 indexed files/137 raw findings47.801s;
final725 files/132 raw findings47.535s, both exit0. All raw records/source indexes
are retained compressed; nra-summary.json selects this surface's records. Old
status-word matches to unrelated Goal/Native families were checked against actual
Plan semantics rather than accepted as proof of domain equivalence. The public
CLI emitted no scan_status/omitted-detector counters, so detector completeness
cannot be certified from those absent fields. No native or DSL equivalence proof;
these are authored ownership/caller patches with executed behavior evidence.

## Remaining independent requirement

**Complete inactive-Agent plan restoration belongs to Tesla142's source custody.**
Current detached surface drops posts and controller.restore retains models/modes/
commands but no plan. This batch tests optional sidebar-panel retirement while
the Conversation stays attached. It does not claim full rich-view retirement is
fixed. Exact source sites and typed contract routed directly to142 in comment
5883172179, recorded in receiving T4 surface; no competing source store added.
No own-scope blocker remains. CI deferred, no unchanged64-tab matrix rerun.

Owned disposable test directories and uncompressed raw scan files are cleaned
only after process audit. Source, compressed evidence and failed terminal logs
are preserved. No worktrees in volatile memory or source under /tmp.
