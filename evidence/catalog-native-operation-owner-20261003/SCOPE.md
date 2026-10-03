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

## Published source closure

Five production files delete30/add26 lines. AgentKind and Command remain the
only catalog declarations; CatalogCommandAction.bind is now the sole native
action-selection owner. AgentModal and Conversation.action_provider_login
consume it directly. StoreScreen consumes the original AgentKind.section and
heading/description to compose its existing native widgets. No class or store
was added; this is removal of schema-to-frontend dependencies, not a reduction
in the number of declared action/agent cases or a claim of full U2 completion.

Before/after source evidence parsed288 production and391 test modules with
zero omissions. The schema has no native import or retired compose/bind method.
Remaining lexical bind/compose sites belong to other source/transport/widget
operations; they are not silently counted as removed. No dynamic resolution
or full external dependency-root claim.

The existing installed catalog journey now supports --catalog-only: the same
real App/Store/AgentModal/editor/PTY completion and cancellation controls run
without the unrelated Pi admission. Its actual installed catalog data is
fixture-owned and removed afterward; original command identity and catalog
membership are preserved. It uses private settings/directories and the
existing resource cleanup. No protocol/UI/model objects are replaced.

534 was released by Mendel but readonly metadata showed only15 Core/SDK
distributions, no Toad or Textual. Nothing was installed there. 485 belongs to
Sch385. Parent authorized existing520 CODE reuse instead; final native App
check awaits its fresh borrower clearance. No new environment or repeated
provider/native gate is being created.
