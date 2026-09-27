# S4 Toad checkpoint, 2026-09-27 America/Toronto

Own worktree /home/ts/wt/toad-s4-read-routing-20260927,
branch codex/s4-mounted-read-basis-20260927, OpenHCSDev/toad fork.
Source base 0894005; implementation b71aa26. Final ordering adjustment publishes
pending proofs after widgets mount, so a concurrent layout callback cannot prune
rows still waiting for the history lock. Both bounded and partial/scroll pilots
pass after that adjustment. Final source commit follows this checkpoint.

Core source a410de9 at https://github.com/OpenHCSDev/agent-comms/pull/137.
Eight mounted pilots and four reader tests passed; no pending source/test issue.
Core final shard 54 passed; all source/evidence retained. No additional workers,
model override, installations, paid-provider calls or deployment. This S4 CLI was
observed at PID 1910606 in its independent service
comms-independent-s4-20260927.service; owner stated previous CLI was absent.

Next publication step only: push own branch and create draft PR explicitly on
OpenHCSDev/toad; record URL and verified remote SHA in the final checkpoint.
Parent owns coupled core/Toad pin refresh and deployment. No new refactor follows.
