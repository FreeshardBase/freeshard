#!/usr/bin/env bash
# test-db-cleanup.sh — tear down leftovers of a hung/aborted pytest run.
#
# The test suite (pytest-docker) starts postgres:17 under compose project
# "shard-core-test" (tests/conftest.py: docker_compose_project_name) with host
# port 5433 pinned (tests/docker-compose.yml). api_client tests additionally
# create the docker network "portal" and real app containers. A killed pytest
# leaves these behind; the next run then fails on the pinned port / stale
# network. This script removes them. It mutates only test resources.
#
# Usage (from repo root): .claude/skills/freeshard-diagnostics-and-tooling/scripts/test-db-cleanup.sh
#   The "portal" network is also used by a real dev shard (`just run-dev`).
#   The script refuses to touch a portal network that still has containers
#   attached unless you pass --force (which force-disconnects them first,
#   mirroring tests/util.py:_force_remove_docker_network).

set -u
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

if [ ! -f tests/docker-compose.yml ]; then
	echo "ERROR: run from the freeshard repo root." >&2
	exit 2
fi

echo "== compose project shard-core-test =="
docker compose -p shard-core-test -f tests/docker-compose.yml down -v --remove-orphans

echo "== docker network 'portal' =="
if ! docker network inspect portal >/dev/null 2>&1; then
	echo "portal network does not exist — nothing to do."
	exit 0
fi

attached=$(docker network inspect portal --format '{{range .Containers}}{{.Name}} {{end}}')
if [ -n "${attached// /}" ]; then
	if [ "$FORCE" -eq 1 ]; then
		for name in $attached; do
			echo "force-disconnecting $name"
			docker network disconnect -f portal "$name" || true
		done
	else
		echo "REFUSING: portal network still has containers attached: $attached"
		echo "If these are test leftovers (e.g. filebrowser/immich/paperless-ngx), re-run with --force."
		echo "If a dev shard is running on this host, do NOT force — you would break it."
		exit 1
	fi
fi
docker network rm portal && echo "portal network removed."
