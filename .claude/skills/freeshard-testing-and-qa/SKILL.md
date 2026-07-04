---
name: freeshard-testing-and-qa
description: "How to run, write, and trust tests in the freeshard (shard_core) repo. Use when running pytest, adding or modifying tests, choosing between the api_client/app_client/db fixtures, overriding config in tests, diagnosing a flaky or hanging test, or deciding what evidence a fix needs before a PR. TRIGGER on: 'run the tests', 'add a test', tests/conftest.py, tests/util.py, pytest-docker, LifespanManager, 'test hangs', 'CI-only failure', 'flaky test', port 5433, 'docker network portal', wait_until_app_installed, TimeoutError in CI. SKIP when: recreating the dev environment / uv sync / worktrees (use freeshard-build-and-env), debugging production behavior rather than tests (use freeshard-debugging-playbook), editing .github/workflows themselves (use freeshard-change-control for gates; this skill only describes what CI runs), or cataloguing config options outside tests (use freeshard-config-and-flags)."
---

# Freeshard testing and QA

This repo is **shard_core**: the FastAPI + PostgreSQL + Docker Compose application that runs on a "shard" (a user's personal cloud VM). The test suite is unusual in two ways: (1) it runs against a **real PostgreSQL container** (never a mocked DB), and (2) its heavyweight tier performs **real Docker operations** — creating networks, pulling images, and installing real apps. Knowing which tier your test belongs in is the core discipline here.

All commands assume CWD = repo root and a synced venv (`uv sync --extra dev` — see freeshard-build-and-env). All facts verified on 2026-07-03 against origin/main (0a40684); suite size then: 137 tests across 36 test modules (134 verified by `--collect-only` at e55ce51, plus the 3 tests in tests/test_backup.py merged since via PR https://github.com/FreeshardBase/freeshard/pull/119).

## Running tests

| Task | Command |
|---|---|
| Full suite | `.venv/bin/pytest tests` |
| Single file | `.venv/bin/pytest tests/test_profile.py` |
| Single test | `.venv/bin/pytest tests/test_app_installation.py::test_install_app` |
| By pattern | `.venv/bin/pytest tests -k 'tours'` |
| Collect only (sanity check, no Docker needed) | `.venv/bin/pytest tests --collect-only -q` |
| Lint exactly as CI does | `.venv/bin/ruff check .` |
| Auto-fix + format (run after any code change) | `just cleanup` |

`just cleanup` runs `ruff check --fix` plus `black` on `shard_core` and `tests` (justfile:4-7). black is not a declared dev dependency but arrives transitively via `datamodel-code-generator` in the dev extra, so it is present after `uv sync --extra dev`.

### Prerequisites

- **Docker daemon with compose v2 plugin.** pytest-docker auto-starts `tests/docker-compose.yml` (postgres:17, db/user/password all `shard_core_test`, host port fixed at **5433**) under compose project name `shard-core-test` (tests/conftest.py:91-98) and tears it down at session end.
- **Internet access.** A session-scoped autouse fixture runs a REAL `docker login` against the registries in root `config.toml` (conftest.py:129-131 → shard_core/service/app_installation/__init__.py:123). The credentials for `portalapps.azurecr.io` are committed at config.toml:30-33. `api_client` tests then really pull `portalapps.azurecr.io/ptl-apps/filebrowser:master` (the filebrowser mock-app zip references it; the other mock apps use `nginx:alpine`). If that ACR credential is ever rotated, every `api_client` test breaks with image-pull failures — that is the first thing to check on a sudden mass failure.
- **No concurrent runs.** Port 5433, compose project name `shard-core-test`, the docker network `portal`, and app container names (e.g. `filebrowser`) are all global on the host. Two worktrees running pytest at once, or pytest next to a locally running dev shard, will collide. There is no pytest-xdist; do not parallelize.

### Cleanup after a hung or crashed run

```bash
# hung/leftover test postgres:
docker compose -p shard-core-test -f tests/docker-compose.yml down -v
# leftover app network (api_client teardown normally removes it):
docker network rm portal
```

If `docker network rm portal` fails with "active endpoints", disconnect containers first — that exact failure mode is why tests/util.py:150-172 force-disconnects every container before removing the network (commit 28964fd "Fix flaky CI: portal network not torn down between tests").

## Fixture decision rule (the core discipline)

Three tiers, defined in tests/conftest.py. **Always pick the cheapest tier that can observe your behavior.** History shows flaky integration tests get demoted to the cheap tier eventually (commits 7e1922e "Fix #45: Convert integration tests to lightweight unit tests", aad605a) — start there.

| Fixture | What it gives you | Cost | Use for |
|---|---|---|---|
| `app_client` (conftest.py:212-238) | FastAPI app via httpx `ASGITransport`, **no lifespan**, no Docker, DB initialized directly + default identity created | Fast | Route + DB tests. The default choice for any endpoint test. |
| `api_client` (conftest.py:183-209) | Full app under `LifespanManager` (startup/shutdown timeout 20s), real docker network `portal`, app-store downloads mocked from `tests/mock_app_store/`, then **really installs the 3 `initial_apps`** (filebrowser, immich, paperless-ngx — root config.toml:39; tests/config.toml does not override it) and waits for them | Slow (tens of seconds each) | ONLY when you need background tasks, real app installation/lifecycle, or the Docker network. |
| `db` (conftest.py:173-180) | `database.init_database()` / `shutdown_database()` only, no HTTP app | Fast | Service-layer / database-layer tests with no HTTP surface. |

Both client fixtures start at `base_url="https://init"`, call `GET /public/meta/whoareyou`, and switch `base_url` to the shard's real domain — so your test requests look like they arrive at `https://<shard-domain>/...`.

### The importlib.reload trap

`api_client` and `app_client` both do `importlib.reload()` on `shard_core.service.websocket`, `shard_core.service.app_installation.worker`, and `shard_core.service.telemetry` because those modules hold global state (conftest.py:186-190, 218-220). **Any mock you create on those modules BEFORE the fixture runs is silently wiped by the reload.** The conftest comment at line 190 says it explicitly: "Mocks must be set up after modules are reloaded or else they will be overwritten." Practical rule: request the client fixture first, patch inside the test body (or in a fixture that depends on the client fixture), never in an earlier-ordered autouse fixture.

## Database semantics in tests

- The postgres container is **session-scoped**; yoyo migrations run once per container lifetime (`_yoyo*` tables are preserved by the truncation).
- An autouse function-scoped fixture **TRUNCATEs all public tables (except `_yoyo*`) with `RESTART IDENTITY CASCADE` BEFORE each test** — not after (conftest.py:145, 159-170). Consequences:
  - A failing test leaves its DB state behind — inspect it post-mortem via `psql "host=localhost port=5433 dbname=shard_core_test user=shard_core_test password=shard_core_test"`.
  - Tests must NEVER depend on rows created by a prior test; that dependency is silently order-sensitive and will break under reordering.
  - Tests do not need to clean up DB state after themselves.

## Config overrides in tests

Settings in tests are `_TestSettings`: root `config.toml` overlaid **per-field** by `tests/config.toml` (conftest.py:54-59). Anything tests/config.toml does not override (initial_apps, registries, app-store URL, management/controller URLs) leaks in from production config — this is intentional but surprising. tests/config.toml speeds things up: app lifecycle `refresh_interval = 2`, last-access `max_update_frequency = 3`, every-second usage-tracking cron.

Three override mechanisms, applied on top of that:

| Mechanism | Scope | How |
|---|---|---|
| Module-level `config_override = {...}` dict | whole test module | conftest reads `request.module.config_override` (conftest.py:139). Supported but currently unused by any test module (as of 2026-07-03). |
| `@pytest.mark.config_override({...})` | one test | See tests/test_docker_prune.py:8-11. The marker is unregistered, so collection emits a `PytestUnknownMarkWarning` — known cosmetic noise, not your bug. |
| `settings_override({...})` context manager | a block inside a test | `from tests.conftest import settings_override` — see tests/test_telemetry.py:46, tests/test_service_init_apps.py. Restores old settings on exit. |

All three take nested dicts mirroring the TOML structure, e.g. `{"apps": {"pruning": {"enabled": False}}}`. Env-var override rules for production config are out of scope here — see freeshard-config-and-flags.

## HTTP mocking of external services

No test talks to the real controller or management API. The `requests_mock` fixture (conftest.py:338-341, built on the `responses` library) repoints settings at `https://management-mock` and `https://freeshard-controller-mock` and fakes: `GET /api/shards/self` (returns `mock_shard`: size XS, max M), `POST /api/shards/self/resize` (returns 409 for sizes l/xl, 204 otherwise), `POST /api/feedback`, `GET sharedSecret`, `POST /app_usage`. To serve a custom shard/subscription payload, use `requests_mock_context(shard=..., subscription=...)` directly (conftest.py:280-327).

`peer_mock_requests` (conftest.py:344-371) fakes a remote peer shard: its `whoareyou` identity endpoint plus wildcard GET/POST on a mock app subdomain — use it for peer-to-peer signed-call tests (see tests/test_call_peer.py, tests/test_signed_call.py).

Both mocks call `rsps.add_passthru("")`, so unmatched requests (e.g. real ACR pulls in `api_client` tests) still pass through.

## How to add a test

1. **File**: `tests/test_<topic>.py`. Async tests are plain `async def test_...` — `asyncio_mode = "auto"` (pyproject.toml:71), no marker needed.
2. **Pick the fixture tier** using the table above. Route test → `app_client`. Only escalate to `api_client` if the assertion genuinely needs installed apps, background workers, or Docker.
3. **App-related tests**: mock apps live in `tests/mock_app_store/<name>/<name>.zip` (available: `filebrowser`, `immich`, `paperless-ngx`, `always_on`, `large_app`, `mock_app`, `quick_stop`). The `api_client` fixture patches `_download_app_zip` and `app_exists_in_store` to serve from there (conftest.py:374-395). A new mock app = new directory + zip containing `app_meta.json`, `docker-compose.yml.template`, `icon.svg`; use `nginx:alpine` as the image (`tests/util.py:20` `WAITING_DOCKER_IMAGE`) so no registry auth is needed.
4. **Controller/management HTTP**: use the `requests_mock` fixture, or `requests_mock_context(...)`/`responses` directly for custom payloads.
5. **Helpers** in tests/util.py: `pair_new_terminal(client)` (pairing-code flow, asserts 201), `install_app(client, name)`, `wait_until_app_installed(client, name, timeout=60)` (2s poll), `wait_until_app_uninstalled`, `retry_async(f, timeout=90, frequency=3)` (retries `AssertionError` by default), `verify_signature_auth` + `modify_request_like_traefik_forward_auth` for HTTP-message-signature tests (RSA_PSS_SHA512 — see freeshard-domain-reference).
6. **Timing**: never assert immediately after triggering a background action. Poll with `retry_async` or the `wait_until_*` helpers; pick timeouts generous for loaded CI runners (see flaky playbook below).
7. Run `just cleanup`, then the affected file, then the full suite if you touched conftest/util (conftest.py is historically the #1 fix-commit file in the repo — changes there ripple everywhere).

## Flaky-test playbook

**Symptom: a test times out in CI but passes locally.** CI runners are slower than your machine. Precedent fixes, in escalation order:

| Fix | Precedent |
|---|---|
| Bump the wait/poll timeout | c824636 "increase app install wait timeout to reduce CI flakiness" — 20s was too tight on loaded GitHub runners; `test_peer_auth_basic` hit TimeoutError in the release pipeline while the PR pipeline passed (PR https://github.com/FreeshardBase/freeshard/pull/64) |
| Set/raise `LifespanManager` shutdown_timeout | dc45ced "set shutdown_timeout on LifespanManager to prevent teardown flakiness" |
| Force-disconnect containers before removing the `portal` network | 28964fd — the current tests/util.py:150-172 logic |
| Demote the test to `app_client`/unit level | aad605a (test_telemetry_recording), 7e1922e (Fix https://github.com/FreeshardBase/freeshard/issues/45) |
| Wait for app install before asserting | f96076f "wait for app installation before auth check in test_headers" |

**Symptom: whole suite hangs in CI.** Precedent: 358a908 "Fix CI test hang: commit migration SQL and guard pool cleanup" (during the Postgres migration). Check migration state and connection-pool teardown first.

**First suspects on a slow runner** — the timing-sensitive tests (all verified to contain real sleeps or tight polling against tests/config.toml intervals):

| Test file | Timing dependency |
|---|---|
| tests/test_app_last_access.py | bare `time.sleep(3)` against `max_update_frequency = 3` |
| tests/test_async_util_periodic.py | asserts counts after `asyncio.sleep(2-3)` |
| tests/test_throttle.py | `time.sleep(0.2)` |
| tests/test_app_lifecycle.py | `retry_async` ceilings vs the 2s lifecycle `refresh_interval` |

There are currently **no skip/xfail markers anywhere in the suite** (a 2022-era skip, dcf6207, was later re-enabled). Do not add `skip` to silence flakiness — fix it with the playbook above or demote the test; freeshard-change-control treats disabled tests as a red flag.

**Symptom: everything with `api_client` fails at image pull.** Check the committed ACR credential (config.toml:30-33) and general internet access before debugging your change.

## Coverage gaps (as of 2026-07-03)

Verified by grepping origin/main's tests/ for module names and routes:

| Gap | Why it matters |
|---|---|
| shard_core/web/protected/backup.py (backup routes) — untested; shard_core/service/backup.py got its FIRST unit tests only in July 2026 (tests/test_backup.py, 3 tests, PR https://github.com/FreeshardBase/freeshard/pull/119) | The backup subsystem is the repo's worst tests-vs-incidents ratio: rclone output/flag handling broke production THREE times (9666db5 in 2024; b9dfcfd rclone-stats validation and 935250b JSONB datetime in 0.38.x, 2026 — neither shipped with a test; then issue https://github.com/FreeshardBase/freeshard/issues/117, all v18 backups failing on an rclone flag missing from the bundled 1.60.1 binary, which finally brought the guard tests). Any change here MUST extend those tests. |
| shard_core/service/portal_controller.py | Legacy backend client, zero coverage. |
| shard_core/service/websocket.py + shard_core/web/protected/ws.py | Websocket routes; conftest reloads the module but nothing exercises it. |

Also flagged in-tree: tests/test_app_lifecycle.py:101-103 has todos for `test_large_app_does_not_start` and an app-size-comparison test (the `large_app` mock app exists for this).

The new tests/test_backup.py is the template for testing subprocess-driven code cheaply: mock `asyncio.create_subprocess_exec` with an `AsyncMock` process, no fixture tier needed at all.

There is **no coverage tooling** (no pytest-cov in deps) — "has tests" is judged by grep, not by a percentage.

## CI: what actually runs

- **snapshot.yml** — triggers on push to `**` AND pull_request to `**`. Runs test.yml (two jobs: ruff, and pytest; both on ubuntu-latest / Python 3.13, installing via `uv sync --frozen --extra dev` and running `uv run ruff check .` / `uv run pytest tests` — as of origin/main 0a40684; older branches still carry the previous `pip install ".[dev]"` variant), then builds and pushes `ghcr.io/freeshardbase/freeshard:<branch-slug>`. Because both events fire for a PR branch, **every PR effectively runs the whole suite twice**.
- The `TEST_ENV` sparse/full input threaded through snapshot.yml → test.yml:42 is **DEAD**: nothing in shard_core or tests reads it (the consuming decorator was removed; last straggler cleaned in 639ba77). Likewise `CONFIG: tests/config.yml` in test.yml:41 is dead — nothing reads `CONFIG` (full evidence: freeshard-config-and-flags). Don't build on either; don't "fix" them in a drive-by either (see freeshard-change-control).
- **release.yml** — triggers on GitHub release created. Gate: release tag must equal `pyproject.toml` version, else the job fails and tells you to run `just set-version <tag>` first. Then tests, then builds in container `ghcr.io/freeshardbase/cicd-image:1.0.3` and pushes `ghcr.io/freeshardbase/freeshard:<tag>`. Two commented-out jobs (`pages` redoc docs, `json-schema` Azure upload) are dead since the GitLab→GitHub migration (skipped in d309113, Feb 2025). Release procedure itself: freeshard-run-and-operate and freeshard-change-control.
- Only secret used anywhere: `secrets.GITHUB_TOKEN` (packages:write for ghcr).

CI green ≠ shipped: merged code reaches shards only via the release flow (see freeshard-change-control, "merged-is-not-shipped").

## What counts as evidence

House discipline for claiming something is fixed or working:

1. **A fix for a failure mode needs a test that reproduces the failure class** — write it, watch it fail, then make it pass. Report both observations. The backup subsystem shows what happens otherwise: the same rclone-handling failure class shipped to production three times over two years (9666db5 → b9dfcfd → issue #117) because no regression test pinned it; the pattern only stopped when the fix for #117 landed together with guard tests (0d42299, tests/test_backup.py).
2. **"Tests pass" means you ran them and read the output**, not that the code looks right. Paste the pytest summary line into your PR description.
3. **A CI-only flake fix needs the CI evidence**, not just a local pass — link the failing run and the passing run after your change (precedent: the c824636 commit message names the exact failing test and pipeline).
4. New work in an untested subsystem (backup routes, portal_controller, websocket) must bring the first tests with it — reviewers will ask.
5. When a test's absence is deliberate (genuinely unmockable external dependency), say so explicitly in the PR rather than staying silent.

## When NOT to use this skill

- Setting up the venv, uv, worktrees, type-sync from freeshard-controller → **freeshard-build-and-env**
- Running the dev server or compose stack, deploying, backup/restore operations → **freeshard-run-and-operate**
- A production symptom (not a test failure) needs triage → **freeshard-debugging-playbook**
- Config/flag catalog, env-override rules outside tests → **freeshard-config-and-flags**
- What may be changed, gates, release rules, PR review expectations → **freeshard-change-control**
- Cross-repo contract changes (controller API shapes the mocks mirror) → **freeshard-ecosystem-contracts**
- Measuring performance instead of asserting correctness → **freeshard-diagnostics-and-tooling**

## Provenance and maintenance

Written 2026-07-03. Verified against origin/main at 0a40684 (confirmed equal to the live remote head via `gh api repos/FreeshardBase/freeshard/branches/main`) plus the local working tree at e55ce51; tests/conftest.py, tests/util.py, tests/config.toml, tests/docker-compose.yml, justfile, config.toml, snapshot.yml, and release.yml are byte-identical between the two, while test.yml and tests/test_backup.py facts were taken from origin/main. Primary sources: those files plus git history and GitHub PRs/issues (hashes and URLs cited inline; all checked with `git log`/`git show`/`gh`).

Drift-prone facts — re-verify before relying on them:

| Fact | Re-verify with |
|---|---|
| 137 tests / 36 modules | `.venv/bin/pytest tests --collect-only -q \| tail -1` |
| postgres:17 on host port 5433, project `shard-core-test` | `cat tests/docker-compose.yml; grep -n shard-core-test tests/conftest.py` |
| initial_apps = filebrowser, immich, paperless-ngx (not overridden in tests) | `grep -n initial_apps config.toml tests/config.toml` |
| ACR creds committed and used by setup_all | `grep -n -A3 'apps.registries' config.toml; grep -n login_docker_registries tests/conftest.py` |
| Reloaded-by-fixture module list (websocket, app_installation.worker, telemetry) | `grep -n 'importlib.reload' tests/conftest.py` |
| Truncate-BEFORE-each-test, `_yoyo*` preserved | `grep -n -B2 -A12 '_truncate_all_tables' tests/conftest.py` |
| TEST_ENV / CONFIG env vars still dead | `grep -rn 'TEST_ENV\|environ\[.CONFIG' shard_core/ tests/ .github/` |
| portal_controller / websocket still untested; backup routes still untested | `grep -rln 'portal_controller\|websocket\|protected/backup' tests/ --include='*.py'` |
| Suite runs twice per PR (push + pull_request triggers) | `head -12 .github/workflows/snapshot.yml` |
| No skip/xfail markers in suite | `grep -rn 'pytest.mark.skip\|pytest.mark.xfail\|pytest.skip' tests/ --include='*.py'` |
| wait_until_app_installed default timeout 60s / 2s poll | `grep -n -A8 'def wait_until_app_installed' tests/util.py` |
| module-level config_override dict still unused | `grep -rn '^config_override' tests/` |
