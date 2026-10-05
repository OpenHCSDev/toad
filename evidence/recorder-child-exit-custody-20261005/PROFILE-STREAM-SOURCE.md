# Original profile/guardian stream and exit path

Qualified02 source ff11a76d has three start_terminal consumers: record's
ordinary branch, profile_launch, and the original OS probe. The ordinary branch
passes terminal.log as stderr. profile_launch omits the stream keywords. The
factory previously forwarded only supplied keywords through ProcessOwner.start
to Core ChildLaunch.spawn, whose stdin/stdout/stderr defaults are DEVNULL. The
terminal guardian therefore discarded its own streams before launch_terminal
requested inheritance for st. The observed empty terminal.log was the profiler
ancestor's log, not st's diagnostic stream.

ProcessOwner.start_terminal now owns inherited standard-stream defaults and
forwards them explicitly. Its three consumers retain their original factories,
resources and publications. An explicit caller stream still overrides the
default. launch_terminal and launch_program already inherit their original
parent streams; no second logger or metadata mirror is necessary. The generic
Core child launch remains unchanged.

Original exit path: ProfileProcess.export sends SIGINT to the original sampler
group, joins and checks its actual wait/export. The original receipt records
signal2 only for sampler679018, export0,117 samples/zero errors. The terminal
and program guardians are separate original sessions. launch_program waits its
actual UI child, finalizes owned cleanup, publishes that child's result, and
returns its returncode to its own Python entrypoint. launch_terminal waits its
actual st child, finalizes cleanup, publishes that result, and returns its
returncode. The supplied publications attest UI0 and st1 with no parent errors.
They do not retain st's direct-child wait or prove that its intermediary program
guardian completed its own interpreter exit successfully.

The recorder exports sampling before CtrlQ. That ordering is recorded, not
promoted to the cause of st1. The original installed st binary's sigchld branch
can fail on a child's nonzero status/signal or wait failure, and ttyread can fail
on a read error. Both diagnostic paths write stderr before exit1. Their presence
in the exact local binary is source evidence, not proof of which branch ran.
The previous default DEVNULL path prevented classifying these alternatives.

UI/st success requirements, forced-exit refusal, startup/deadline budgets,
export timing, signals and outcomes are unchanged. Two source modules compile
without imports. Previous full Package parse288+397+41+1310 and Core324 remains
context; PROFILE-STREAM-AST.json records the new original Package/caller closure.
PROFILE-STREAM-QUALIFICATION.json proposes only the changed stationary profile
case with fresh original public admission. No new execution is authorized or
performed by this checkpoint. Ordinary and the three OS cases are accepted and
not proposed for repetition. Both original failures remain preserved.
