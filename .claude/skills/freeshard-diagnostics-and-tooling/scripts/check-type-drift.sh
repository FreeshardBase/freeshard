#!/usr/bin/env bash
# check-type-drift.sh — report drift between shard_core/data_model/backend/*
# (the local copy of freeshard-controller's data_model, synced by `just get-types`)
# and the controller's origin/main, WITHOUT needing the sibling checkout.
#
# Read-only: fetches remote files via `gh api contents`, diffs against the local
# copy with the 2-line "# DO NOT MODIFY" header stripped.
#
# Usage (from repo root):  .claude/skills/freeshard-diagnostics-and-tooling/scripts/check-type-drift.sh
# Exit code: 0 = fully in sync, 1 = drift found, 2 = setup error.

set -u

LOCAL_DIR="shard_core/data_model/backend"
REMOTE_PATH="freeshard-controller-backend/freeshard_controller/data_model"
REPO="FreeshardBase/freeshard-controller"
REF="${1:-main}"

if [ ! -d "$LOCAL_DIR" ]; then
	echo "ERROR: $LOCAL_DIR not found — run from the freeshard repo root." >&2
	exit 2
fi
if ! command -v gh >/dev/null; then
	echo "ERROR: gh CLI required." >&2
	exit 2
fi

remote_files=$(gh api "repos/$REPO/contents/$REMOTE_PATH?ref=$REF" --jq '.[] | select(.type=="file") | .name') || {
	echo "ERROR: could not list $REPO:$REMOTE_PATH@$REF via gh api." >&2
	exit 2
}

drift=0
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

for f in $remote_files; do
	gh api "repos/$REPO/contents/$REMOTE_PATH/$f?ref=$REF" --jq '.content' | base64 -d > "$tmp/remote"
	if [ ! -f "$LOCAL_DIR/$f" ]; then
		echo "MISSING LOCALLY : $f (exists on controller $REF, not in $LOCAL_DIR — next get-types adds it)"
		drift=1
		continue
	fi
	# get-types prepends "# DO NOT MODIFY - copied from freeshard-controller\n\n";
	# empty files (e.g. __init__.py) get no header, so strip conditionally.
	if head -1 "$LOCAL_DIR/$f" | grep -q '^# DO NOT MODIFY'; then
		tail -n +3 "$LOCAL_DIR/$f" > "$tmp/local"
	else
		cp "$LOCAL_DIR/$f" "$tmp/local"
	fi
	if diff -q "$tmp/local" "$tmp/remote" >/dev/null; then
		echo "in sync         : $f"
	else
		echo "DRIFTED         : $f"
		diff "$tmp/local" "$tmp/remote" | sed 's/^/    /'
		drift=1
	fi
done

# Files that exist locally but not on the controller anymore (removed upstream).
for lf in "$LOCAL_DIR"/*.py; do
	name=$(basename "$lf")
	if ! printf '%s\n' "$remote_files" | grep -qx "$name"; then
		echo "EXTRA LOCALLY   : $name (gone from controller $REF — next get-types removes it)"
		drift=1
	fi
done

if [ "$drift" -eq 0 ]; then
	echo "RESULT: backend type copy is in sync with $REPO@$REF"
else
	echo "RESULT: DRIFT — before relying on these types: cd ../freeshard-controller && git checkout main && git pull, then 'just get-types' here (destructive rm -rf + copy)."
fi
exit $drift
