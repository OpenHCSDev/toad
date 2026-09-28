# Toad fork refactor

Plans for refactoring the `OpenHCSDev/toad` fork by OpenHCS standards: upstream Toad's own code as well as what the fork added. Put this directory in the fork at `docs/refactor/`.

## Read in this order

1. **[00-RULES.md](00-RULES.md):** binding on every agent. No compatibility, aggressive deletion, total completion, tests only where they protect behaviour, plus Toad's specifics (upstream is dormant; Textual's and ACP's contracts are honored; agent-comms is ours and changes in lockstep).
2. **[01-INDEX.md](01-INDEX.md):** the evidence, the surfaces, their order, and decisions TD1 and TD2.
3. **Surface files,** written one at a time, just before each is dispatched.

Agents working on Toad get the same prompt addendum as agent-comms' round 2, pointing at this directory instead.
