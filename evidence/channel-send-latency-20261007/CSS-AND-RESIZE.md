# Native CSS path demand and real sidebar resizing

Native PR95 is merged. Stylesheet publication borrows the selector declaration's
existing target-only versus relational distinction. Target-only rules avoid
constructing ancestry; relational rules and virtual components retain their
original paths. No new cache, geometry exception or layout suppression.

The selected frontend keeps the delivered navigation source and backend cohort.
All 953 installed assets match committed sources/wheels, all 69 package versions
match, and all 2856 RECORD rows check. A real private four-view App passed
navigation, retained incarnation, hidden prompt and completion behavior.

One isolated st capture opened an existing saved agent, opened the real peer,
returned to the original, scrolled and hid/restored the right panel, and dragged
both native sidebar edges out/back. No input was submitted. Recorded owned
processes joined; the original source owner identity was unchanged.

Raw evidence: `/home/ts/.cache/agent-scratch/css-path-agent-sidebar-resize-20261007`.
The fixed left drag changed width 71→78→69 columns (percentage rounding); the
right changed 60→68→60. This is single width jumps, not continuous drag acceptance.

Observed cold mount/selection was 314/406ms; initialize 1859ms and load 263ms.
Warm return was 37ms. This sampled run does not demonstrate a speedup over the
earlier unprofiled run. During width gestures, original layout passes took
65/70ms left and 62/45ms right, almost entirely CPU, followed by additional
passes. Resizing remains slow. The sample profile has 225 sampling errors and
cannot provide reliable function attribution; focused layout profiling is next.

Only the native CSS source fix, dependency selection and existing recorder
journey are changed. The pending native Widget work is excluded. Publication
through the existing frontend owner follows this affected installed check;
running windows and the original backend are preserved.
