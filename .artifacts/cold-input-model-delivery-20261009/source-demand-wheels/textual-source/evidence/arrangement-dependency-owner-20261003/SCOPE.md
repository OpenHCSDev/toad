# Native arrangement dependency ownership

Normally integrated merged main Text39 `2d1e2efa`; its receipt and installed
artifact remain frozen. Same isolated checkout, no new environment or recording.

Widget.arrange currently owns _height_arrangement_cache, while
NativeLayoutHeight.depends calls the same arrangement dependency algorithm
outside that lifetime. Native auto-size and optimal-width measurement can walk
that child's dependency tree before arrange repeats the same question.
The existing Widget resource must own this question for every consumer.

Promote its acquisition to a Widget method; have both arrange and the native
measurement policy derive the answer there. Keep the genuinely different box
question and unknown/custom hooks conservative. Retain the original geometry,
child-list and layout mutation inputs. No second cache, map, class or policy flag.

Original384 profile at21.143s shows native box→content height→arrange→grid box;
this is source-path evidence, not CPU duration or proof of dominance. Reuse the
existing ProfileTrace and NRA Package parser. Source reasoning and whole-family
implementation precede one affected sanity batch; installed qualification joins
Heisenberg's next changed workflow, never a repeat of frozen384.

Heisenberg owns Toad/recording; Kepler owns native Widget/measurement consumers.
Full End, smoothness, channel first paint and CPU closure remain open.

## Working source checkpoint

Two production files: 23 added /16 deleted. Existing Widget now acquires its
original _height_arrangement_cache once per child-list, geometry and layout
epoch. NativeLayoutHeight.depends and Widget.arrange both consume that answer.
The standalone arrangement_depends_on_available_height algorithm and import
are deleted. The original presentation-retirement path still releases this
resource. Flow/Grid/Stream and custom hook declarations keep their existing
polymorphic algorithms; the separate box-dependency question is not collapsed
into arrangement dependency.

The before/after AST uses existing Package/ParsedModule across 249 native and
288 Toad production modules, zero parse omissions. The former free algorithm
has no remaining declaration/import/call; one Widget acquisition method and
one original resource write remain. AST does not establish dynamic receiver or
MRO resolution. Instance monkeypatches are outside the existing class-bound
measurement contract; no new compatibility path was introduced.

One affected final native sanity batch: 68 passed in4.97s. It exercises native
height/box/arrangement equivalence, grid tracks/extrema, inherited and structural
invalidations, unknown/custom hooks and cache retirement. Initial invocation
named a nonexistent test file, ran zero tests and is retained separately; this
was a command error, not a source behavior failure. No assertions were weakened,
no test harness or environment was created, no UI/provider run repeated.

Qualification completed in Heisenberg's joined391 installed workflow below.
The original384 profile is partial and proves a matching source path, not a CPU
share or measured performance gain. Text39's scoped Ready receipt and frozen
installed source remain unchanged. End, discrete motion and channel first paint
remain open; this draft does not claim their closure.

Normal main integration298cbe3e9 retained production byte equality with d1bae228c.
No semantic conflict or affected source change; no repeated checks or recording.
The two-file follow-up is now based on main rather than the closed Text39 branch.

## Original screenshot palette consumer closure

Parent granted the disjoint App export consumer in this same scope. Original
38902 evidence is preserved:
`/home/ts/wt/toad-regression-widget-cost-20261001/evidence/settings-native-projection-owner-20261003/installed02/settings-subtype-edited.svg`.
It contains161 real text nodes, with black text and canvas after the app selected
ansi-light. A black Cairo conversion is not evidence of absent native widgets.
Exact retained pair: Corea24f696/Toad8939b694/Text2d1e2efa/native2bfb.

App.export_screenshot rendered the original compositor, then omitted Rich's
terminal theme argument; Rich selected its separate SVG_EXPORT_THEME. It now
uses existing App.ansi_theme. Startup's duplicate dark/light palette selection
is deleted in favor of that same owner. Save/deliver/action/document screenshot
consumers already derive from export_screenshot and need no second change.
Content, StylesCache, tint and opacity already consume the same App palette.
The standalone _doc.rich formatter has its own Console, not an App, so it keeps
its actual distinct export contract. No codec, color copy, export override or
new palette resource was added. AST before covers249 native modules/zero
omissions; after records the changed original App consumer, with unchanged
other roots. Dynamic resolution is not established by AST alone.

Three focused checks pass in0.45s: existing reactive palette selection plus real
composed App export using configured dark/light palettes and the original SVG
text node's CSS fill. The first check incorrectly assumed a CSS red edit would
be that default glyph's exported color; its 1pass/2fail result is preserved.
The corrected check asks the actual export-owned fact: native default foreground
maps through the app's current configured palette. Production code did not
change between those checks. No provider, physical recording or original SVG
was replayed or altered. Installed family qualification is recorded in the single joined391 workflow
below. The specific installed ANSI-light export observation remains unverified;
no separate movie is required for it.

Cumulative production scope is three files:25 added/21 deleted. Text39/384's
qualified artifact and the independent390/39 release stay protected. No default
activation or installed export success is claimed from these native checks.

## Scoped Ready: joined391 installed workflow

Exact production source `0ab687e007fca311ce9f786634d8f5fc991ff808` is unchanged.
Textual source/assets byte equality266files and original directURL were verified
in the reused normal69 installed holder. The four package inventories match:
Core `5e1575269bd20e87f6c03365619feeb0178a215d`,
Toad `38ede873b675756d995e0da5e7c4d89bf9e36819`, Textual0ab above,
Diff `8fa7d4d0db993ea3b761c2760ca9b6a56a6251e9`; ACP0.12.1, trusted native51b.
No new environment/native build, source overlay, dependency bypass or default
publication. Toad391's subsequent integration retained its affected body family.

Source proof:
`/home/ts/wt/toad-viewport-raster-cpu-continuation-20261001/.artifacts/staging-retained-publication391-native40-20261003/source-proof.json`.
Original joined receipt:
`/home/ts/wt/toad-viewport-raster-cpu-continuation-20261001/evidence/retained-publication391-native40-20261003/READY.json`.
Raw recording:
`/home/ts/.cache/agent-scratch/retained-publication391-arrangement40-public-20261003-01/capture`.

The continuous recording completed in113.418s. All16 warm-history and7 native
input/paging checks passed;41 original ready body resources were retained.
Actual saved A/B/A history, prepared resources, draft, Undo, reader positions and
held PageUp/PageDown/reversal were checked. The A-return PNG was reviewed
directly and is readable. Existing installed App checks covered all3 body
implementations with a pending native writer: retained rows, cost/selection,
width/style/LRU changes, worker identity and queued/cancelled publication.
The original owner birth identity remained unchanged/alive, runtime unchanged,
cleanup remaining[]/errors[]. Encoder255 is retained separately from terminal
custody; no explicit application exit0 is inferred.

Exact held input-Up20.396–22.181s writer intervals: median13.4ms, p9528.4ms,
maximum202.19ms. Heisenberg viewed consecutive moving frames while UI was alive: motion
remains chunky. Kernel marker/export Up77.82%, idle23.48%; those windows include
profiling/observer work and are wider than the physical held keys.1294 GIL
samples/0errors remain partial coverage. No matched-workload CPU gain, FPS,
smoothness, full End/revoke/receipt closure or broad performance claim.
Channel first paint was still Loading at1s. Original355/38902 negatives remain.

The configured light/dark native App SVG checks passed after this source change,
but this joined recording does not establish the specific installed ANSI-light
export case. That narrow observation is stated separately from the qualified
native measurement/body workflow. No repeated gate or provider run was started.
