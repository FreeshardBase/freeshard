#!/usr/bin/env bash
# verify-env-override.sh — prove that a FREESHARD_* env var actually lands in Settings().
#
# Why this exists: pydantic-settings uses env_nested_delimiter="__" (DOUBLE underscore,
# shard_core/settings.py). A single-underscore nested var is SILENTLY ignored — this
# shipped a production bug once (commit 5de2998: self-hosted compose used
# FREESHARD_DNS_ZONE, shards silently fell back to zone "freeshard.cloud").
# Run this whenever you add a FREESHARD_* var to docker-compose.yml, justfile, or CI.
#
# Usage (from repo root):
#   .claude/skills/freeshard-diagnostics-and-tooling/scripts/verify-env-override.sh FREESHARD_DNS__ZONE=example.test dns.zone
#   .claude/skills/freeshard-diagnostics-and-tooling/scripts/verify-env-override.sh FREESHARD_PATH_ROOT_HOST=/srv/x path_root_host
#
# Arg 1: VAR=value assignment. Arg 2: dotted Settings attribute path.
# Exit code: 0 = override landed, 1 = it did NOT land, 2 = usage/setup error.

set -u

if [ $# -ne 2 ]; then
	echo "usage: $0 FREESHARD_SECTION__FIELD=value section.field" >&2
	exit 2
fi
ASSIGN="$1"
ATTR_PATH="$2"
VAR="${ASSIGN%%=*}"
VAL="${ASSIGN#*=}"

if [ ! -f "shard_core/settings.py" ]; then
	echo "ERROR: run from the freeshard repo root (Settings loads config.toml CWD-relative)." >&2
	exit 2
fi
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

ACTUAL=$(env "$VAR=$VAL" "$PY" -c "
from shard_core.settings import Settings
obj = Settings()
for part in '$ATTR_PATH'.split('.'):
    obj = getattr(obj, part)
print(obj)
") || {
	echo "ERROR: Settings() failed to construct or attribute path '$ATTR_PATH' is wrong." >&2
	exit 2
}

if [ "$ACTUAL" = "$VAL" ]; then
	echo "PASS: $VAR=$VAL -> Settings().$ATTR_PATH == '$ACTUAL'"
	exit 0
else
	echo "FAIL: $VAR=$VAL was IGNORED -> Settings().$ATTR_PATH == '$ACTUAL'"
	echo "      Most common cause: single underscore where the nested delimiter needs '__'."
	echo "      Correct form: FREESHARD_<SECTION>__<FIELD> (e.g. FREESHARD_DNS__ZONE)."
	exit 1
fi
