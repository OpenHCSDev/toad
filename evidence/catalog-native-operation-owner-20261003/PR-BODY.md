## Changed

The existing StoreScreen owns native catalog composition; the existing
CatalogCommandAction selects and binds native actions to the original Command.
AgentKind retains section membership and FieldCodec catalog decoding. Both
AgentModal and provider-login consume the action owner directly.

Five production files delete30/add26 lines. Removed schema widget creation,
schema native-action resolution and all old consumers. No class, registry,
copied command value, codec or compatibility export was added. This removes
schema-to-frontend dependencies; it is not a full headless/frontend rewrite.

## Source and acceptance

Existing refactor-audit Package.load before/after evidence covers288 production
and391 test modules with zero parse omissions. Lexical bind/compose overlap is
read semantically; no dynamic/dependency-root completeness claim.

Final installed01 actual App/Pilot/catalog/editor/real shell PTY passed:
original grouping and command identity; selector/editor cancel; exit7;
edited install preserves source; hyphen/arbitrary/declaration-only actions;
local login completion; held PTY cancellation; same Store catalog return.
Pip check69, installed headless catalog import and typed action sanity passed.
Source/wheel/installed319 Toad assets equal; qualified Core574342/Text38266
assets equal their wheels. Existing520 CODE holder reused and released;
original metadata/native/evidence/UNKNOWN preserved. No new environment.

See evidence/catalog-native-operation-owner-20261003/READY.json,
installed-source-proof.json, installed01.log, installed01/catalog-only-receipt.json,
cleanup.json and reviewed PNGs. Six unchanged PTY EOF OSError(5) log messages
are retained; command process/reader terminal assertions passed. Cleanup has
seven inaccessible unrelated environment reads, not a zero-gap global census.

This is installed native App/PTY acceptance, not physical st, ACP/native-Pi
admission, account authentication, provider, performance or full U2/U4/U5
acceptance. Zero Pi/provider inputs/public publication. CI deferred.
