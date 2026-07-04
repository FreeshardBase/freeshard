#!/usr/bin/env bash
# churn-hotspots.sh — rank files by change frequency (churn) and by how often
# they appear in fix-commits. High fix-count files are where the next bug is.
#
# Rename handling (this repo has two big ones that break naive counting):
#   - portal_core/ -> shard_core/            (commit 88e5842, 2025-02-11)
#   - shard_core/model/ -> shard_core/data_model/  (commit b5b4eda, 2025-08-04)
# Paths from old commits are normalized to their current names, and only files
# that still exist (git ls-files) are counted, so dead files don't pollute the list.
#
# Usage (from repo root):
#   .claude/skills/freeshard-diagnostics-and-tooling/scripts/churn-hotspots.sh            # full history
#   .claude/skills/freeshard-diagnostics-and-tooling/scripts/churn-hotspots.sh --since 2026-01-01
# Read-only.

set -u

SINCE_ARGS=()
if [ "${1:-}" = "--since" ] && [ -n "${2:-}" ]; then
	SINCE_ARGS=(--since "$2")
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
	echo "ERROR: not inside a git checkout." >&2
	exit 2
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git ls-files > "$tmp/live"

normalize() {
	sed -e 's|^portal_core/|shard_core/|' -e 's|^shard_core/model/|shard_core/data_model/|'
}

echo "== top 20 by total churn (commits touching the file) =="
git log "${SINCE_ARGS[@]}" --format= --name-only \
	| grep -v '^$' | normalize | grep -Fxf "$tmp/live" \
	| sort | uniq -c | sort -rn | head -20

echo
echo "== top 20 by fix-commit count (subject contains fix, case-insensitive) =="
git log "${SINCE_ARGS[@]}" -i --grep 'fix' --format= --name-only \
	| grep -v '^$' | normalize | grep -Fxf "$tmp/live" \
	| sort | uniq -c | sort -rn | head -20

echo
echo "Interpretation: a file high on BOTH lists is a defect hotspot — read"
echo "freeshard-failure-archaeology before touching it, and expect review scrutiny."
