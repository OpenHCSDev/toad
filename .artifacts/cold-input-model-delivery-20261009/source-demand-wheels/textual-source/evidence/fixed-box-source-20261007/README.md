# Fixed native box source

The native fixed/fill box resolver reads its own styles and supplied size,
viewport and fractions. It does not measure descendants. Previously its cache
generation still included descendant layout changes. The existing local style
dependency owner now supplies this distinction; the existing box cache binds
these results to the actual RenderStyles object and generation. It retains that
object so replacement and object lifetime cannot alias an unrelated source.

Intrinsic sizing, fractional width with greedy=False, custom style getters and
custom scalar resolvers retain full layout invalidation. Native spacing and
border inputs are required for the narrower source. Parent auto-size and parent
lifetime remain inputs. Held mutation-box admission remains first. Width,
viewport and fraction variants remain separate. Original extrema are restored
on cache hits. Repeated generation fields were removed from individual keys:
the owning cache already retires its previous generation.

The complete consumers are Widget._get_box_model and
box_depends_on_available_height; presentation release already retires the style
dependency and box sources. Related tests now check stale results and actual
cache lifetime instead of duplicating internal key shape. Existing Package
analysis parsed 250 production modules without omissions.

Final related controls: 34 passed in 2.63s, using this native source. Coverage
includes descendant changes, style-source replacement, intrinsic versus fixed
sizing, fractional greedy modes, custom Scalar/RenderStyles behavior, extrema
restoration and held geometry. An attempted Spacing-subclass control failed at
declaration because the actual accelerated Spacing is not subclassable; that
invalid control was removed. Its original failure log is preserved.

One original raw-driver resize App used source 623e07dd with the existing
installed Toad/Core runtime, without changing packages. It reached width 60,
released capture, exited zero and produced empty stderr. Final width appeared
at 993.66ms; matching earlier installed observation was 1057.70ms. Layout counts
were 69 versus 61. Different work and profiling overhead mean this does not
establish a reliable latency gain. Width frames still take roughly 100ms.
The subsequent source changes only decline non-native spacing/border inputs and
name the already-used tuple fields; the App's native-input path is unchanged.

Full App output and profiles remain at
/home/ts/.cache/agent-scratch/native-box-source-20261007. The original fixture
owns joined teardown; exact individual child births were not recorded. This is
source/App acceptance, not an installed or physical speed claim. There were no
provider calls, public inputs or package writes. Parent owns integration and
durable delivery. Required width-dependent rewrapping and arrangement remain.
