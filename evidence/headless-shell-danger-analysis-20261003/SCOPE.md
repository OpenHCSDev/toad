# Headless shell danger analysis

Existing CommandVisitor/CommandAtom/DangerLevel owns shell command analysis and
path escalation. Its module still imports Textual Span because detect mixes
analysis and native span conversion/CSS defaults. Importing core classification
therefore loads the frontend. U2 requires a headless behavior owner, not a
cosmetic file move.

Keep the same existing bounded cache on analyze, returning immutable typed
CommandAtom tuples. Native PromptTextArea.highlight_shell constructs native
spans and supplies frontend CSS through the existing DangerStyles/DangerLevel
hook. Delete detect and its defaults/native import, migrate its one production
caller and original classifier checks. No new owner type, cache, registry,
semantic store, policy threshold or protocol/native change.

Reasoning includes parse/path failure, cache lifetime, nested shell scope,
source span coordinates and actual native prompt paint. Existing cache capacity
and external bashlex grammar are preserved. All related imports/callers are
enumerated by existing NRA Package AST before editing; zero parse omissions.
AST cannot establish dynamic resolution. Existing native ContextNode raw SDK
reference was rejected as a false mirror lead; it remains unchanged.

After coherent implementation: one proportionate classifier/import batch and
actual installed App prompt highlighting using a released holder. No new
provider/input/WT/environment. Cold ContextTree595 gate is a distinct pending
installed dependency; do not replace its saved original with warm metadata.

## Qualified checkpoint

35 production lines deleted, 20 added in two existing owners. The original
parser-only unsupported/parse failure boundary and filesystem OSError boundary
remain separate. Native CSS/defaults and spans are owned by the original prompt.
Normal397 integration preserves Coreb068/Text42/native89 and normal69 dependencies.
One actual installed App/Pilot check passed: unsent warning draft, original native
spans, physical Pilot tab return, original setting toggles. It did not execute a
shell command or submit input. Headless import and the original two classifier
checks passed together after implementation. 928 installed source assets match;
no source overlay, direct URL forgery, new environment/native or provider request.
No latency/fullheadless claim. Before/after AST is source evidence, not dynamic proof.

Separate terminal06 proves cold saved context, actual reference disclosure and
roster Ready with the original stopped-source producer. It preserves terminal05
full failure and prelaunch01-04 mistakes, not an erased/replayed input.
Raw receipts remain under named agent scratch; originals and UNKNOWN untouched.

The package-source metadata helper initially compared a typed PackageDirectUrl
to a dict and treated its declared string location as a Path; an interrupted
builder had not written the Toad inventory. These packaging errors are retained
in READY. They were corrected at existing typed codec/record consumers before
publication, without changing product behavior or repeating the App gate.
The cleanup receipt reports unreadable process environments explicitly. No
known active test/recorder handles remain; the temporary run root is empty.

This is a scoped U2 checkpoint (BOUND separation), not whole headless completion.
