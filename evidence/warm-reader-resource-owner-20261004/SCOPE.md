# Unchanged loaded-reader resources across logical tab cohorts

Source-only successor of #443 at f3fb7ebc2878ed946f1217f2d38872d34c219d91.
No prefix, package, App, provider, native input or physical recording access.
#443's published qualifier and installed-only projection control stay unchanged.

## Existing owner and consumers

`ReaderCheckpoint` was confined to the saved-state A/B/A control. It already
owned editor/document/history, reader position, composited message text, weak
Markdown body references and the original render-cache resources. The existing
4/16/32/64 control checked attachment/editor/queue/painted-answer continuity but
could pass without proving unchanged native body/cache reuse at those cohorts.

The original class now lives with the existing recent-reader control and is
consumed by both the saved-state and logical-cohort controls. Capture observes
the current source; the saved-state caller retains its original non-tail scroll,
draft, history checkpoint and Undo setup. No snapshot method changes user state.
The checkpoint additionally observes the original committed page instances and
their prepared fragment tuples, tail intent and actual unsent text. Its original
reader binding owns raw page-read observation for both consumers (IMPL-12).
No competing checkpoint implementation, new fixture, loader or renderer exists.

Each logical cohort captures the two actual loaded native sources before its
three visit phases. Every unchanged loaded-source return must retain the
observed fragments, Markdown/render resources, reader/editor and composited
message text, and perform zero additional raw page acquisition. New input and
queue delivery follow these visit phases; the next cohort captures the genuinely
changed source anew. Blank logical tabs never earn loaded-history credit.

## Scope and remaining qualification

These are authored localhost-response controls on the existing installed
App/ACP/native fixture. They are not configured-provider, terminal-pixel,
CPU-gain, all-64-loaded-history or runtime PASS evidence. Captured reader
positions are reported; a tail-only source cannot earn a non-tail claim.
The original configured SDK fork, readonly guards and input dispositions remain
unchanged. Full continuous startup/channel/unopened-thread/fork-before-answer/
reply/notification/queue/status workflow and velocity/reversal/growing-End/
warm returns remain unfinished until their actual admitted executions.

The complete original refactor-audit Package census covers 288 Toad production,
395 tests, 41 tools and 249 retained native59 production modules, with zero parse
omissions. Lexical references were read against their existing owners; external
dynamic aliases and runtime equivalence are not proved by AST.

No private holder is requested or reserved by this source checkpoint. Public444
style22 is protected; any future qualification needs an eligible actual floor,
its archive/origins/keepers and a specific granted purpose. No old1470 restore.

## Observer lifetime correction

The e0a source preview retained strong page, fragment and native render-cache
identity witnesses through later input/resource sampling. Weak Markdown body
references did not eliminate those graph edges. No runtime resource claim was
qualified by that preview.

The two existing consumers now bound their genuine witnesses to unchanged
return assertions. The cohort control records scalar reader positions, clears
the checkpoint dictionary in finally and deletes it before new input, queue
handling, object counts or RSS observation. The saved A/B/A control keeps the
witnesses through all final warm/Undo assertions, clears the list in finally,
and exits that function before the next journey phase. Its loop locals end
with the same scope. Identity assertions and original raw-read assertions are
unchanged; no value-equality substitution or identity-number oracle was added.

Original Package covers288 production,395 tests,41 tools with zero omissions;
original native59 dependency249/0 remains unchanged. Every original assertion
AST in both consumers is equal before/after, and diff/parse checks pass.
Production/pins are unchanged. No App, provider, input, build or holder purpose
was used; configured continuous/cohort/resource acceptance remains unqualified.

## Actual merged443 normal integration

Normally joined actual main443 dd7b5a389106e69ad4dbc02340834d3b36448bd4
at4a10010d90fa0015c514bc038d80f264d4a349cb. All #446 production, controls,
tools and pins remain byte-equal the d1d16de1 observer-lifetime checkpoint.
Original443 ONE installed App and whole handback stay at their frozen scope.
No App, build, package or native purpose is inferred by this source join.

## Original configured readonly warm consumer

The existing `readonly_saved_reader_pilot.warm_pages` separately maintained
page/native-child/editor/reader return decisions (IMPL-12). It now borrows
`ReaderCheckpoint` from its original caller. The shared owner also captures
and verifies each page's actual committed `fragment_views` by identity, so
removing the old child comparison does not weaken its contract. Raw page
acquisition is observed through the original reader binding. The independent
prepared-work key, bounded resource, compositor-frame observation and final
parked source disposal checks remain in their original control.

`private_original_warm` establishes a genuine non-tail reader and authored
unsent draft/Undo state before acquiring the checkpoint and opening the
original channel target. The first channel return and subsequent actual tab
returns use that same predeparture checkpoint; none recaptures a baseline
after returning. Native Undo/Redo must preserve the original editor document
and history. Both direct callers release the borrowed checkpoint in finally;
auxiliary native strip/cache witnesses end before parked disposal and the
function exits before any subsequent resource observation.

This remains the original configured SDK-fork fixture's readonly callback.
Its owner capture, authenticated configuration, source journal, native input
refusal and whole-child disposition contracts are unchanged. No configured
model submission, input replay, artificial-history seed or new fixture was
introduced. The localhost streamed-response controls remain distinct from
this original configured-source control. Source integration alone proves
neither control's runtime, provider, queue nor continuous workflow result.

The existing configured fixture command is
`tests/readonly_saved_reader_pilot.py --private-original-warm`; it is an
unexecuted source operand, not an eligible prefix or purpose grant. Any actual
execution needs its current installed-source and original fixture/native
custody bound to a fresh specific purpose. No accepted #443 App/build/movie
is repeated and no holder is accessed by this checkpoint.

### Prompt binding correction before execution

The d007/a894 source preview selected native Ctrl+Y for Redo. The full Toad
binding owner makes that unsafe: `SubmitNowAction` declares Ctrl+Y with
priority for Send now. This control now invokes the inherited native editor
`redo()` method after actual Ctrl+Z and retains the exact document/history/
text assertions. It does not dispatch a submission key, change production
bindings, simulate a provider response or weaken the readonly fixture guard.
The prior source/evidence remains historical and unexecuted; its native-only
Ctrl+Y description is explicitly superseded by this complete binding read.

## Future installed operands after ordinary447 acceptance

Normally joined actual main447 `3dc801984c211d2739c4c96c5907e068cd25820c`
at `778b30a917fcfbc1dfafac4a254095da5a724265`; that join changes only
receiving evidence, with zero production/control/tool/pin delta versus9a75.
The accepted PUBLIC447 ordinary18-check receipt and AFTER review stay frozen.

`FUTURE-INSTALLED-CONTROL-OPERANDS.json` binds determining source
`7e9ed795554ce8cb873d5ebea0d088da6419f8ae`, three original control paths,
SHA256s, argv/environment/output operands and original helper source hashes:

| Existing entrypoint | Exact authored scope |
| --- | --- |
| `saved_state_user_journey_pilot.py --warm-only` | The original localhost preparation/channel/unopened-gamma stream prerequisites and actual warm A/B/A/Undo assertions. Stops after their existing completion; adaptive/fork/reply phases are not invoked. Default remains the full localhost journey. |
| `native_session_retention_pilot.py` | 4/16/32/64 logical tabs, exactly two loaded native histories and blank remainder, original localhost queue/owner checks. Witnesses end before new input and resource observations. |
| `readonly_saved_reader_pilot.py --private-original-warm` | Original configured/authenticated >=40MB SDK fork callback, non-tail draft/Undo, first and later unchanged-source returns and final parked disposal. Existing readonly custody requires zero native inputs; no configured answer/queue credit. |

The new warm option routes the same acceptance callback to its original
completion point (IMPL-12); no second fixture or warm oracle exists. The
configured fixture now carries its captured `L0A_EVIDENCE` path through its
existing retained-environment replacement, so original reader failure files
remain writable. No authentication/model/source field changes.
Original assertion ASTs are unchanged: saved65, mixed22, readonly25,
shared checkpoint31, original configured fixture29. Original Package covers
288 production/395 tests/41 tools without omissions; the original before
context additionally parses published Core324/native59 249 without omissions.
These are source coverage and parse/diff checks, not runtime acceptance.

The interpreter is deliberately unbound until a real eligible NONLIVE prefix
and fresh purpose are issued. Outputs are named but not created. Configured
capture uses only the original cutover helper directory on PYTHONPATH; it
adds no product src overlay, and its original reader subprocess removes
PYTHONPATH. Three listed entrypoints do not authorize three Apps or reserve
a holder. The active W6 purpose and PUBLIC334/current447 remain protected.
The current production/build inputs remain equal to the original retained
443 wheel's Git producer; no rebuild, wheel/prefix access or accepted App
repeat occurred.

Two-loaded mixed cohorts do not prove 4/16/32/64 genuinely loaded histories.
Full configured startup/unopened/channel/tab/fork-before-answer/reply/
notification/queue/status/history, cold initial width, real velocity/reversal/
growing End and full held-scroll/warm-return physical obligations remain open.
The TC1 presentation acquisition lead remains a separate source pass after
this checkpoint: pre-mount binding and the derived native widget relation
must survive; no presentation/native source was changed here.
