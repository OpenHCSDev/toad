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
