# Fixed boxes under width changes

The native arrangement resolver visits child box measurements when a container
changes width. `_get_box_model` previously keyed every measurement by that
container width and its width fraction, including explicit fixed boxes whose
original scalar/extrema resolver cannot read either input.

The existing `_local_box_inputs` declaration now supplies this answer alongside
its height/content/style answers, from the same original RenderStyles generation.
The existing box measurement resource omits parent width only for proved native
local boxes. No second measurement or geometry cache was added. Both consumers
and Widget teardown were migrated; the old height-only style-resource name is
deleted. Parent identity/auto sizing, viewport, actual height, styles, extrema
and constrained-width behavior remain inputs. Fill, auto content, percentages,
fractions, cross-axis width units, custom resolvers/styles and the non-cell
maximum-width zero-parent exception remain conservative.

Source trace covered `_resolve_box_models`, native vertical/horizontal placement,
Widget arrangement/measurement/resize/refresh, DOM ancestor invalidation,
Compositor placement/held/intrinsic resources, Scalar resolution and extrema.
The existing Package AST reader parsed 250 native modules without omissions.
Source search found two `_local_box_inputs` consumers plus the original teardown
resource release; all were migrated together.

Wrapping is a separate required answer. Auto-height content measures at its new
width; layout needs those heights to position following children and establish
scroll extents before painting. Native TextArea also rebuilds wrapping on resize.
Its public document can be independently mutated, so equal wrap width alone does
not certify unchanged text. No width-only shortcut or readiness bypass was added
to that family, and this change does not remove its synchronous work.

## Results

- **32 measurement checks passed, 1.76s**, including exact fixed-box resource
  reuse and style replacement, width-relative values, constraints, viewport
  units, custom extrema and the zero-width auto-parent exception.
- **Original raw-driver drag App exit 0, empty stderr** using this native source
  and the released native-layout-lifetime author runtime. Final width 60,
  capture released, final paint 852.16ms, 16 frames, 57 Layout messages,
  732 initial / 650 final widgets. No provider input or package change.
- Parent's installed baseline was 803.64ms with 802 initial / 662 final widgets.
  Different work was present; **no reliable latency improvement is claimed**.

Original unchanged driver:
`/home/ts/.cache/agent-scratch/sidebar-drag-hotpath-20261007/drag-settled.py`.
Results: `/home/ts/.cache/agent-scratch/native-parent-width-20261007/`
(`native.log`, `app.stdout.log`, `app.stderr.log`, `drag01/result.json`).
The original fixture owns private cleanup. Exact child birth records were not
collected. No installed or live qualification is implied by the source App.

## Auto-content review

The published predicate already requires `styles_only`, which excludes both
auto width and auto height. It also excludes fractional width. Therefore an
independent-width answer implies no width-content call and `local_styles=True`
for both greedy modes. Custom auto-height measurement cannot receive the
normalized width key. No production correction or extra guard was added.

Two additional real native controls passed: auto width with a genuinely relative
`1fr` child expands from 30 to 50; a custom auto-height method reading parent
width returns 60 then 100. Both keep distinct measurement resources.
`auto-content-review.log` retains the custom-height pass and first invalid
auto-width setup; `auto-width-mounted-review.log` retains the explicit refusal
of that setup. Inline `50%` is normalized to Unit.WIDTH by ScalarProperty and
does not enter the original relative-child expansion predicate. The corrected
control uses the original fractional declaration and awaits child mount before
asserting that required relation; `auto-width-relative-declaration-review.log`
records its pass (0.41s). No accepted drag App was repeated.
