# Point queries borrow the original ordered scene

Native owner: Compositor in `_compositor.py`. Heisenberg owns Toad frame
callback custody and defer consumers; there are no Toad or Screen edits here.
Same isolated checkout, normally integrated merged Text49. No new environment,
cache, map, resource flag, type, provider call or recording.

Read the original415 profile and the whole input/hover/selection publication
chain before editing. The reverse phase includes a `layers_visible` activation;
it is an observed stack transition, not CPU time, call count or dominance.
Original receipt and film remain unchanged.

`get_widget_at` and `get_widgets_at` each acquire `layers_visible`, expanding
every visible widget across every screen row before answering one coordinate.
Both separately decide clipped membership and visibility. The existing
`get_widgets_at` owns that algorithm using the original front-to-back
`visible_widgets`; `get_widget_at` derives its first result. Delete the unused
row projection, retained field and all lifecycle resets. Screen/App hover,
pointer, focus, click, tooltip, style, content offsets and native Pilot consume
these unchanged APIs. Toad sidebar/menu callers do likewise. Source retirement
controls must consume actual point queries rather than deleted internal rows.

Preserve layer order, original regions, region-and-clip containment, screen
y bounds, live visibility, no-hit outcomes, loading/focus/selection hooks and
ordinary scene invalidation. Queries remain synchronous on the original scene.
Repeated mouse events on an unchanged scene may scan more widgets than the old
row index; removing whole-screen row expansion is not a measured speedup.
No arbitrary threshold or substitute spatial index is added.

Existing NRA Package parses complete native and Toad production roots, with
before/after declarations, writes and consumers. Report omissions explicitly;
AST names cannot resolve all dynamic receivers or third-party private access.
Patterns IMPL-12/13: one membership procedure owns all point projections.

Source reasoning and complete implementation first. Final bounded controls
protect overlapping and clipped hits, hidden widgets, live scroll/reflow,
retirement, hover/focus/click/selection and screen edges in actual native Apps.
One changed installed journey joins Heisenberg's next meaningful source batch;
no old415 film/check repeat. Full motion/CPU/144Hz/IRC/DM/cold-warm scope stays open.

## Working source and final controls

Production commit `ad30eda1f8937f909bc80aa84ff1a91b63a7bb2f`: one native
production file, **5 added /44 deleted**. `get_widgets_at` is the sole point
membership algorithm. `get_widget_at` consumes its first result and retains
NoWidget. Membership uses the original region and clip directly; no per-widget
intersection allocation or per-row expansion is required by a point query.
The retired row property, its field and all seven invalidation writes are gone.
Existing layer, visible-region and scene lifetime resources remain the owners.
The source-retirement control now warms and reads those actual point APIs.
No Toad, Screen, CSS or callback source changed.

Before/after AST: native249 modules, targeted sites70→55; Toad288 modules,
24 unchanged targeted sites; zero parse omissions. Row-property/field sites
16→0 across both production roots. Native Screen/App routing, pointer hover,
focus, tooltip, styles and content offsets keep their original APIs; Toad's
sidebar and menu use those same APIs. Static names cannot prove dynamic plugin
resolution, and removed internal compositor rows have no compatibility reader.

Final native controls ran in one bounded original-App/Pilot batch: **17 passed,
one fixture failed in3.32s**. Original `_arrange._build_layers`/`arrange` lays
out each layer separately; the new fixture had incorrectly applied an extra
−3 vertical offset to the front layer. Corrected only that fixture and reran
only that failed control: **1 passed in0.51s**. Production bytes did not change.
The initial log/exit and corrected log/exit are retained separately. No whole
batch repeat, synthetic geometry, mocked compositor, backend or protocol path.

The18 qualified cases detect these concrete risks:

- overlapping front-to-back hits, container clip and screen edge errors;
- hidden, moved and retired widgets continuing to receive input;
- inactive vertical/stream scenes retaining removed widgets or old paint;
- click/hover/mouse-down/mouse-up selecting covered rather than visible widgets;
- native ancestor focus and OptionList hover enter/leave routing regressions;
- TextArea cursor targeting and double-width text-selection offsets.

Existing system Python/dependencies only; the headroom warning was proportionate
to one bounded3.32s batch and its0.51s fixture correction. No new environment,
installed-prefix mutation, provider input, recorder or public owner action.
The next changed Heisenberg frame-callback/Toad journey supplies installed
qualification. Draft/source-qualified only; no speed, CPU, FPS or smoothness
claim and no repeat of the already-qualified415/49 film.
