# S4 Toad checkpoint, 2026-09-27 America/Toronto

Own worktree /home/ts/wt/toad-s4-read-routing-20260927,
branch codex/s4-mounted-read-basis-20260927, OpenHCSDev/toad fork.
Source base 0894005; implementation b71aa26. Final ordering adjustment publishes
pending proofs after widgets mount, so a concurrent layout callback cannot prune
rows still waiting for the history lock. Both bounded and partial/scroll pilots
pass after that adjustment. Final source commit: e9a0542486b946a0ab24f645751266eb3693dd48.

Core source a410de9 at https://github.com/OpenHCSDev/agent-comms/pull/137.
Eight mounted pilots and four reader tests passed; no pending source/test issue.
Core final shard 54 passed; all source/evidence retained. No additional workers,
model override, installations, paid-provider calls or deployment. This S4 CLI was
observed at PID 1910606 in its independent service
comms-independent-s4-20260927.service; owner stated previous CLI was absent.

Published draft https://github.com/OpenHCSDev/toad/pull/77. Remote source head
e9a0542486b946a0ab24f645751266eb3693dd48 verified before this evidence-only commit.
No remaining implementation or mounted-validation step. Artifacts preserved.
Parent owns coupled core/Toad pin refresh and deployment. No new refactor follows.
