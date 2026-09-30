# Coherent C3 inactive stage recipe

Execute only after Arendt supplies the final reviewed, merged442 Core head,
the dependency and lock are updated, and that source checkpoint is pushed.
Use one fresh persistent inactive stage. Never modify the accepted firstUI
stage, its receipts, or public launchers. Parent432 owns public activation.

The existing firstUI `requirements.txt` is the accepted frozen68 package
baseline, not the new cohort pin list. Derive all three component pins from
the committed source declaration; retain the other65 exact package versions.

From the clean PR231 worktree, after the final source checkpoint:

```sh
python - <<'PY'
from pathlib import Path
import subprocess, tomllib
source = tomllib.loads(Path('pyproject.toml').read_text())['tool']['uv']['sources']
toad = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
assert subprocess.check_output(['git', 'status', '--porcelain'], text=True) == ''
assert source['agent-comms']['rev'] not in (
    '000a31c562b6d048e26e288b24fcd3f1ac64f803',
    '095fc9c92b6adc8d1cd2ef3ca62a5d567baf8817',
), 'Final reviewed merged442 pin must be supplied before staging'
assert source['textual']['rev'] == '2e49cb838af44d69aa5a6d76b2a1d74cfbe67347'
replacement = {
    'agent-comms': 'agent-comms @ git+' + source['agent-comms']['git'] + '@' + source['agent-comms']['rev'],
    'textual': 'textual @ git+' + source['textual']['git'] + '@' + source['textual']['rev'],
    'batrachian-toad': 'batrachian-toad @ git+https://github.com/OpenHCSDev/toad.git@' + toad,
}
baseline = Path('evidence/first-ui-end-keypad-20260930/requirements.txt').read_text().splitlines()
assert len(baseline) == 68
lines = [replacement.get(line.split(' @ ')[0], line) for line in baseline]
Path('.artifacts').mkdir(exist_ok=True)
Path('.artifacts/c3-release-requirements.txt').write_text('\n'.join(lines) + '\n')
PY
uv lock --check
/home/ts/bin/agent-resource-check --assert-headroom
uv venv --python 3.14 .artifacts/installed-c3-release
uv pip install --python .artifacts/installed-c3-release/bin/python --link-mode hardlink --no-deps -r .artifacts/c3-release-requirements.txt
uv pip check --python .artifacts/installed-c3-release/bin/python
uv pip freeze --python .artifacts/installed-c3-release/bin/python
```

Verify the installed noneditable component/source identities and accepted
frozen package set through the existing stage inspection. Record exact stage,
pins, SDK and the existing trusted nativee36 package in **one staging receipt**.
Use `RuntimeSelection.publish_verified_stage` in
`tests/tools/record_installed_tui.py` on that same receipt. It publishes the
immutable activation metadata and invokes the existing recorder runtime/native
preflight before handoff; do not assemble an independent pin list or live phase.

Native package remains:
`/home/ts/.local/share/agent-comms/native-current-e36a1dde326b7017/node_modules/@earendil-works/pi-coding-agent`.

New installed acceptance is separate from historical firstUI and233 evidence.
Reuse the existing affected journey owner and raw receipt; no optional repeated
provider, compaction, full performance, or source-hash suites. No current
default/package mutation or public owner restart is part of this recipe.
