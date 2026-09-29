# Q6 paired session and renderer deletion

72 old production lines deleted across db/render_protocol/render_zmq (the two
FieldCodec subclass implementations and all callers). 77 deleted including the
five migrated test lines. No aliases remain. SessionTimestampStorage and
SessionMetaStorage use the canonical codec; existing session strings and private
renderer UUID/captured-task/captured-result formats are preserved.

Path/timestamp and UUID/task/result representations are explicit capabilities on
their fields. The only record encoder/decoder is core FieldCodec. Renderer pickle
is accepted only by explicit private transport capture fields. A new task inherits
the existing task family and works without codec/transport edits.

Installed noneditable paired candidate imports are recorded in imports.json.
Mounted saved session/PTY acceptance passes; a read-only SQLite backup preserves
all 46 original session identities/agent definitions/directories and every raw
row remains unchanged. The actual private ZMQ renderer and two real Toad App
instances reuse the same renderer, preparing Markdown, native diff, file preview
and Read tool content. Focused declared-family test passes.

The initial optional renderer-dependency setup failure is retained separately.
After installing the actual declared dependencies, both family and real renderer
UI paths pass. No provider calls or live user history modifications were made.

Paired core PR supplies Annotated field capabilities and the no-codec-subclass
guard. Parent owns the final latest-pair native/ACP/user-entry and live gate.
Fresh-fork socket readiness remains independently owned by Noether/Wegener.
