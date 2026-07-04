#!/usr/bin/env bash
# todo-scan.sh — find code-debt markers in this repo.
#
# Two traps this script exists to avoid:
#   1. ALL markers in this repo are LOWERCASE ("# todo:"). An uppercase-only
#      scan (TODO|FIXME, what most scanners default to) returns ZERO hits.
#   2. Plain `grep -r` from repo root sweeps .worktrees/ (stale agent worktrees
#      with duplicate hits) and data/eff_large_wordlist.txt ('hacker' matches
#      'hack'). `git grep` only searches tracked files of THIS checkout, and we
#      exclude data/ explicitly.
#
# Usage (from repo root): .claude/skills/freeshard-diagnostics-and-tooling/scripts/todo-scan.sh
# Exit code: 0 always (a scan with hits is not a failure).

set -u

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
	echo "ERROR: not inside a git checkout." >&2
	exit 2
fi

EXCLUDES=(':!data' ':!*.lock' ':!tests/fixtures' ':!*.png')
echo "== todo/fixme/hack/xxx markers (case-insensitive, tracked text files; data/, fixtures excluded) =="
git grep -inI --color=never -E 'todo|fixme|hack|xxx' -- "${EXCLUDES[@]}" | grep -vE '^\S+:[0-9]+:.*https?://' || echo "(no markers found)"
echo
echo "== count by file =="
git grep -icI -E 'todo|fixme|hack|xxx' -- "${EXCLUDES[@]}" || true
