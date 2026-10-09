# Grid measurement inputs

`GridLayout.arrange` queries content width and outer-size width extrema only
for auto columns without column spans. It queries content height and outer-size
height extrema only for auto rows without row spans. Final boxes and offsets
receive the resolved cell size. `GridHeight` previously treated all four
operations as incoming-height inputs even when the tracks never called them.

The existing dependency declaration now follows those actual query branches.
The original Widget arrangement resource can reuse measurement placements at
another available height when the grid does not read that height. Width,
viewport, child membership, layout/style publication and optimal mode remain
in the original resource key. Fractional/height-relative rows, height-relative
columns, actual auto-track measurements/extrema, custom layout hooks and
dock/split/overlay placement retain their original dependencies. No compositor,
held-root, clipping or hit-map decision changes.

Source census: 250 production modules parsed, zero omissions, using the existing
refactor-audit Package. The supply/consumer family is GridLayout.arrange,
Layout.__init_subclass__, GridHeight, NativeLayoutHeight and
Widget._arrangement_depends_on_available_height/arrange. There is one changed
production owner, GridHeight; no new retained resource or event cache.

Fourteen affected grid controls passed in 1.07 seconds. New real App controls
compare reused placements against fresh placement and retain custom incoming-
height behavior when the corresponding track changes to auto. The first
height-control assertion incorrectly expected a fixed-height child to fill
the larger auto track; it was corrected to make the child auto-height when
testing that dynamic measurement. Production was unchanged by that correction.

One existing raw-Driver sidebar App check passed with the existing installed
WorkerStatic declaration cohort and native source override. It completed 36
packets, 625 final widgets, width 60, no reported App error. Raw result and
profile remain at:

`/home/ts/.cache/agent-scratch/sidebar-drag-hotpath-20261007/grid-track-input-source-drag/`

Compared with the supplied installed profile, arrangement calls were 760 to
661 and box calls 721 to 643, but root reflows were also 11 to 9. Inclusive root
arrangement was 412 to 337 ms and box time 262 to 244 ms; these overlap. Final
headless paint was 1121 to 937 ms, while posting took 712 to 805 ms. This is
not a reliable overall latency improvement or terminal-pixel acceptance.
The new declaration is source-qualified and the affected App path works;
installation belongs to Parent's integration. Transcript remeasurement at
genuinely changed widths remains required.
