# Initial message publication

Prepared conversation Markdown now acquires its original body worker during
mount, while the body message pump observes completion after mounting. Native
Markdown keeps its default complete-document mount promise (Textual #116).
There is no copied readiness state or new queue.

Source range acquisition joins the actual part publications. Viewport paging
honors its existing native frame receipt before choosing another source edge;
preview extents cannot repeatedly admit the remainder of the message.

The first matched run exposed excessive admission: 23 mounted parts, 568
widgets. Joining part workers alone did not solve it. After the frame receipt
correction, the run mounted four parts, 224 widgets; posting took 8.4 ms and an
actual App callback ran 0.73 ms later while preparation was pending. Preparation
still took 2.88 seconds. These are single source-App measurements, not physical
frame pacing or installed/live claims.

The existing paged nested-Markdown App control passed in 13.98 seconds:
posting 3.56 ms, body readiness 2.08 seconds, nested text and links, original
source copying, native scrolling/reversal, retirement and warm paint identity.
The redundant second update of the constructor's source was removed.

Raw measurements: `/home/ts/.cache/agent-scratch/dm-mount-frame-profile-20261008`.
App result: `/home/ts/.cache/agent-scratch/dm-mount-source-20261008`.
Earlier excessive-admission runs remain in `dm-mount-profile-20261008` and
`dm-mount-acquisition-profile-20261008`; none were overwritten.

Publication and installed acceptance follow through the existing frontend
publication owner. The backend and active native agent sessions are separate.

The candidate build passed all installed asset, origin and RECORD checks, but
the installed paged control timed out retiring the older body. The first source
run passed; this installed negative is not dismissed. Its receipt records a
LiveBody with 23 parts. A subsequent narrowed source run also failed, with no
viewport worker pending and a PresentedFrame with no deferred callbacks. The
frame wait now applies only to range admission, so it does not block retirement;
the remaining exposure/reader relation still needs its actual geometry trace.
The candidate is unpublished and the previous launch default is unchanged.
Raw failures remain in `dm-mount-installed-20261008` and
`dm-mount-retirement-source-20261008` under the owned scratch directory.
The added geometry trace (`dm-mount-geometry-source-20261008`) confirms the old
body is actually offscreen and not interaction-protected. The reader is at the
native bottom with follow intent, no anchor, no viewport worker and no deferred
frame callback. Retirement acquisition, rather than mistaken exposure or a
still-pending frame, is the remaining investigation.

The capture trace found nine missing hidden paragraph resources, with no lock,
stream or geometry barrier. The actual readiness handler notified the viewport
only for retirement capture; completing a visible paragraph did not resume a
viewport that had returned while awaiting its readiness. The registered body
now derives both visible and capture demand through the same viewport owner.
No new readiness flag, worker, queue or native geometry is introduced.

The corrected original App check passed in 14.04 seconds: post 4.95 ms,
readiness 2.15 seconds, exact source/link text, actual wheel/reversal/stop,
retirement and warm identity. Raw result is retained at
`/home/ts/.cache/agent-scratch/dm-visible-publication-wakeup-corrected-20261008`.
Two runner setup refusals occurred before App entry (missing pytest, then the
host native package taking precedence); neither invoked an application attempt.

The packaged successor at production head b6a0fe336 passed the same original
App check in 15.60 seconds: posting 3.26 ms, readiness 2.70 seconds, original
text/links/copy, wheel reversal and stop, native retirement and warm identity.
The command imported Toad and Textual from the candidate installation, not the
source checkouts. The helper receipt's historical source-scope label is unchanged;
this is installed App evidence, not physical terminal or saved SDK acceptance.
Raw result: `/home/ts/.cache/agent-scratch/dm-visible-installed-20261008`.
All 954 package assets, full 69 distributions and 2857 RECORD entries match.
The native wheel was reused exactly; only changed Toad was rebuilt.

## Cold eviction development (not installed)

The viewport previously captured complete paint for unadmitted live bodies and
then discarded it at budget trimming. ReleasedBody now distinguishes that
pending native-child release from CapturingBody. The existing budget supplies
admission, source custody owns pruning, and MeasuredBody retains the original
extent for later reconstruction. Visible/protected demand revokes cold release;
warm admission retains the complete capture requirement. No second queue/cache
or source store is added. MaterializingBody carries admission through its
original preceding resource. The shared retirement lifetime check replaces
repeated guards on the existing body owner.

The existing 32-body App control now crosses the original widget budget using
nine paragraphs per body, initializes the original private protocol, and waits
for its actual presentation/retirement. Its old Static-render copy expectation
was migrated to the existing native selection contract, also in the related
mounted-history control. Source Package AST: 288 modules, zero parse omissions.

Four bodies were observed cold-evicted without captured pixels, but the complete
lifecycle check is NOT qualified: the final run hit the original 12-second
settlement deadline. Earlier startup/count and placeholder-copy negatives are
retained. Raw runs: `dm-cold-eviction-{source,acquired-source,completion-source,
selection-source}-20261008` under `/home/ts/.cache/agent-scratch`, with logs in
`sidebar-drag-hotpath-20261007`. No deadline was raised or failure waived.

Removing the parser prewarm barrier was also rejected: warm preparation was
1.99 seconds versus 1.80 in the baseline, with more live widgets at readiness.
Prewarming and native publication have distinct lifetimes; the original code
was restored. Raw: `dm-single-acquisition-profile-20261008`.
