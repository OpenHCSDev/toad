# Stream native scene changes through the existing damage owner

Stacked after frozen scoped43. Same checkout and installed dependencies; no new
environment, recording, provider, scene map, cache, state flag or type.

Existing Compositor._damage_geometry will compare the original previous and
new scene maps, retain both old and new clipped damage, and derive resized
widgets in that same pass. Full reflow, viewport reflow and lazy full_map must
all consume it. Remove their three MapGeometry symmetric-difference producers
and full reflow's independent common-widget/resize classification. ReflowResult
and Screen's ordinary hide/show/resize behavior remain their existing owners.
MapGeometry.visible_region owns clipped damage rectangles.

NRA Package parses all249 native production modules, no omissions. Read the
existing MapGeometry, all three scene publications, geometry-query consumers,
Screen resize event delivery and damage-to-chop publication before editing.
Dynamic receiver resolution is not proven by AST. Pattern IMPL-12: delete the
repeated change algorithm through its existing owning class.

The original399 trace observes viewport reflow/arrangement during moving keys;
it does not establish this operation's CPU share. Semantic source shows eager
hashing and allocation of both complete maps' geometry records and a second
resize pass. Remove that work without altering legitimate layout/concurrency.
No measured gain claim. Final bounded native sanity and one changed installed
journey follow coherent source closure; do not rerun accepted399/43.

## Working source checkpoint

Production `fa3fe3b2dcfc9a1776342ee02e063eb08dfe3a66`:31 added /25 deleted
lines in `_compositor.py`, relative to frozen43. No43 source was changed.

Existing `_damage_geometry(before, after, owner)` compares each new record
with its original previous record. Changed common widgets supply old and new
clipped rectangles and resize membership. New widgets supply their new damage;
removed widgets supply their old damage. Existing full-screen dirty membership
skips rectangle work as before; its local result is not a stored state flag.
MapGeometry.visible_region supplies each clipped rectangle. All three existing
publication callers take the original map pair, including lazy geometry before
it replaces the current scene. Screen hide/show/resize delivery remains unchanged.

After source evidence uses the same NRA Package:249 native modules, zero parse
omissions. All three geometry-record XOR expressions are gone; Screen's unrelated
entered/exited widget-set XOR remains legitimate membership work. The first
evidence-query attempt included an empty symbol from its BinOp sites and failed
at a Module node; corrected the query, not the production/parser coverage.
Dynamic callback dispatch remains a semantic read, not an AST proof.

## Final proportionate native batch

The existing system Python/source was reused once, after implementation:

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 timeout 45s python -m pytest -q -p no:cacheprovider tests/test_compositor_frame_damage.py
```

Actual exit0, **8 passed in0.79 seconds** (native-sanity.log). The new actual
native App case checks both old/new damage and resized membership on movement
plus width change, then original hide/show and damage on removal/reintroduction.
The existing resize-frame/caption cases cover all three publication paths;
Unicode/sparse paint and nonzero body capture check resulting damage consumers.
No UI/protocol mock or alternate application was introduced.

## Scoped installed qualification from the single changed402/44 run

The same installed run completed in140.423 seconds: all16 warm checks and7 input
checks passed,38 ready body resources retained, original native owner unchanged,
runtime unchanged, cleanup remaining/errors empty. No rerun was made. The ordinary
69-package pair used Coref4a582,Toad613da,Textual3ad603,SDK0.12.1,diff8fa7 and the
original native89b56/tree4b7f package. Existing normal source/assets/directURL/full
native trust proof is referenced in READY.json; the installed compositor bytes
also matched this checkout. Encoder255 remains in the original cleanup receipt;
UI/st process custody was transferred to installed ObservedProcess, not claimed
as an explicitly observed exit0.

Input-focused Up writer median/p95/max12.56/29.89/174.74ms; Down10.09/25.30/97.65ms;
focused-history reversal11.37/22.60/117.73ms. These original writer receipts are
not input-to-pixel latency, FPS or smoothness proof. The1342-sample GIL profile
reported0 errors. Its transition groups identify source activity only, never
CPU time. Kernel phase UI values include diagnostic/observer work; no CPU gain
is claimed.

Personally viewed original48-frame sheets live-14-7 (Up23.193–23.993s) andlive-21-12
(Down47.429–48.229s) AFTER the UI had exited. Both supplied /proc entries were
absent before and after the views. The missing-process branch did not log an
exact UTC for those first two probes; the following timestamp at19:14:32.777836UTC
(monotonic530511954891805ns) confirmed both absent. Parent separately found the
recorder alive earlier while UI was already gone. Encoding-time alive checks
are not personal DURING inspection. Readable body/chrome, repeated positions
and discrete advances are visible; no full-body blank is evident in these two
bands. Personal DURING review remains unestablished. No repeat for optics.

Scoped Ready: original scene damage/resize caller closure and retained saved-UI
workflow are qualified. Motion remains chunky; full CPU/FPS144Hz, fresh live
input/receipt/compaction and broader original performance scope remain open.
Normal current-main merge includes accepted43 and changes no44 production bytes.
Recorded399/43 and every failed/historical proof remain immutable.
