# Existing catalog operations own native composition and binding

U2 source at main55ecaa9a still makes the schema construct native resources:
AgentKind.compose imports Store widgets; Command.bind chooses native action
members. These are frontend operations, not catalog decoding, identity or
platform selection. Native StoreScreen and CatalogCommandAction already own
the rendering and action behavior, respectively.

Keep AgentKind.section, declarations and FieldCodec catalog decoding intact.
Move the one shared section composition into StoreScreen.compose_agents.
Move action declaration selection and binding into CatalogCommandAction.bind;
AgentModal and the existing provider-login action borrow that native owner.
Delete both schema methods and all their callers in the same batch. No new
types, registry, copied command values, compatibility exports or codec.

Existing refactor-audit Package.load parsed the entire production/test roots
before edits. before-owner-consumers.json includes lexical declarations,
imports and calls; generic bind/compose names are ambiguous and require source
reading. No dynamic-resolution or dependency-root completeness claim.
Patterns BOUND-2 and AGENT-2: make existing owners carry their operations and
finish their consumers. This extends the prior headless schema/import work;
native preferences and actual UI resources retain their frontend contracts.

Implement first; then one batched source/import sanity and an affected installed
real App/catalog selector/editor/PTY check using an already released package
holder. No new environment/worktree, configured provider call, native Pi input,
public/default change or unrelated CSS/viewport work. Parent owns publication.
