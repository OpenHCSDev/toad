#!/usr/bin/env bash
# Merge a reviewed toad PR only if the Qt inheritance ratchet passes on that exact head.
#   tools/merge_reviewed.sh PR_NUMBER
# Fetches the PR head into a throwaway worktree, runs tools/qt_inherit_ratchet.py there with the
# agent-comms runtime (it has PySide6), and merges with --match-head-commit only on exit 0.
# A head that moves after the check fails the merge instead of landing unchecked code.
# A head that does not contain current origin/main is refused: its renders and ratchet
# describe a tree that is not what main becomes, so the branch must rebase first.
set -euo pipefail
pr=${1:?usage: tools/merge_reviewed.sh PR_NUMBER}
head=$(gh pr view "$pr" --json headRefOid -q .headRefOid)
runtime=$(ls -td "$HOME"/.local/share/agent-comms/runtimes/*/ | head -1)
check=$(mktemp -d)
trap 'git worktree remove --force "$check" >/dev/null 2>&1 || true' EXIT
git fetch -q origin main "pull/$pr/head"
if ! git merge-base --is-ancestor origin/main "$head"; then
    echo "REFUSED: #$pr head ${head:0:9} does not contain origin/main $(git rev-parse --short origin/main); rebase it first" >&2
    exit 1
fi
git worktree add -q --detach "$check" "$head"
echo "ratchet on #$pr @ ${head:0:9}:"
( cd "$check" && QT_QPA_PLATFORM=offscreen PYTHONPATH=src "${runtime}bin/python" tools/qt_inherit_ratchet.py 2>&1 | grep -v propagateSizeHints )
gh pr merge "$pr" --squash --admin --match-head-commit "$head"
gh pr view "$pr" --json state,mergeCommit -q '"#\(.number // "") \(.state) \(.mergeCommit.oid[0:9])"'
