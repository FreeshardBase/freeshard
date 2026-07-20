---
name: freeshard-diagnostics-and-tooling
description: "How to MEASURE things in the freeshard (shard_core) repo instead of eyeballing them: runnable scripts for type-drift vs the controller, env-override proof, todo scanning, hung-test cleanup, and churn/fix hotspots; plus techniques for fd headroom, OOM-vs-crash discrimination, on-the-wire proxy inspection, disk-space semantics, and GH board/issue queries that actually work. TRIGGER on: 'is the backend type copy stale', 'did my FREESHARD_* env var take effect', 'find todos', 'un-wedge hung test infra' (for the symptom itself — tests won't start — see freeshard-testing-and-qa first), 'which files are bug hotspots', 'measure fd headroom', 'discriminate OOM-kill from self-abort', 'capture what the proxy actually sends', 'disk_space_low semantics', 'query the Dev Board', 'gh issue view fails with projectCards', profiling with yappi. If all you have is a raw symptom string (a 'too many open files' loop, a crashing container), load freeshard-debugging-playbook first. SKIP when: you are diagnosing a specific known failure symptom and want the answer, not a measurement (use freeshard-debugging-playbook); you need config semantics/catalog (freeshard-config-and-flags); you need test-suite architecture or how to add tests (freeshard-testing-and-qa); you need the type-sync PROCEDURE across repos (freeshard-ecosystem-contracts)."
---

# Freeshard diagnostics and tooling

Purpose: replace "it looks fine" with a number or a diff. Every section gives a command, what it measures, and how to read the output. All commands assume CWD = repo root (`/path/to/freeshard`, the shard_core repo). Verified against the repo on 2026-07-03.

Terms used once: **shard** = a customer VM running this repo's app (shard_core: FastAPI + PostgreSQL + Docker Compose orchestration behind a Traefik reverse proxy). **controller** = the central management service (separate repo, FreeshardBase/freeshard-controller). **Dev Board** = the org-level GitHub Projects v2 board where triage actually lives (labels are not used for triage).

## Script index (in `scripts/` next to this file)

All scripts were run and their output verified on 2026-07-03, except `test-db-cleanup.sh` (inherently mutating; syntax- and logic-verified, component commands tested read-only).

| Script | Measures | Mutates? |
|---|---|---|
| `check-type-drift.sh` | Drift of `shard_core/data_model/backend/*` vs controller origin/main | No (gh api reads) |
| `verify-env-override.sh` | Whether a `FREESHARD_*` env var actually lands in `Settings()` | No |
| `todo-scan.sh` | Code-debt markers (lowercase-aware, noise-filtered) | No |
| `test-db-cleanup.sh` | — (teardown of hung test Docker resources) | Yes, test resources only |
| `churn-hotspots.sh` | Git churn + fix-commit hotspots, rename-corrected | No |

Run them as e.g. `.claude/skills/freeshard-diagnostics-and-tooling/scripts/check-type-drift.sh`. Do not confuse with the repo's own `scripts/` dir (it contains only `generate_traefik_dyn_config_model.py` — see "Repo-native tooling" below).

## 1. Type drift vs the controller — `check-type-drift.sh`

**What it measures:** `shard_core/data_model/backend/` is a verbatim copy of the controller's `data_model/` package, made by `just get-types` (justfile:13-23: `rm -rf` target, `cp -r` from the LOCAL sibling checkout, prepend a 2-line `# DO NOT MODIFY` header to every file). Nothing in CI checks freshness. Stale copies have shipped real bugs: `Profile` re-serialization silently dropped billing fields the controller had added (fixed in commits 6d4b101 and e55ce51 — `Profile.from_shard` now uses `getattr(..., default)` defensively, shard_core/data_model/profile.py).

The script diffs each local file (header stripped) against the controller's **origin/main via `gh api contents`** — it does not need or trust the local sibling checkout, which is exactly the failure mode (`just get-types` from a stale checkout produced bidirectional drift in `subscription_model.py`).

**Expected output** (real output, 2026-07-03 — this drift is currently live):

```
in sync         : shard_model.py
MISSING LOCALLY : diagnostic_model.py (exists on controller main, not in shard_core/data_model/backend — next get-types adds it)
DRIFTED         : permission_model.py
    23a24,25
    >     OPEN_DIAGNOSTIC = auto()
    >     RUN_DIAGNOSTIC = auto()
DRIFTED         : settings_model.py
    12a13
    >     NEW_INSTANCE_IMAGE = auto()
DRIFTED         : subscription_model.py
    62d61
    <     approval_url: str | None = None
    65a65
    >     plan_id: str | None = None
RESULT: DRIFT — ...
```

**Interpretation:**
- `MISSING LOCALLY` / lines prefixed `>` = controller is ahead; the next `just get-types` (after pulling the sibling checkout!) picks them up.
- Lines prefixed `<` on a DRIFTED file = the local copy has content main no longer has — a past sync ran against a diverged checkout. Treat the remote as truth.
- Drift is only *operationally* urgent if shard_core loads the drifted model. As of 2026-07-03 shard_core imports the backend copy directly in 4 modules: service/telemetry.py, service/portal_controller.py, service/freeshard_controller.py, data_model/profile.py (+ tests) — but only 2 backend files directly (shard_model, telemetry_model), and `shard_model` itself transitively imports permission_model, subscription_model, and telemetry_model (backend/shard_model.py:9-11). So the currently-drifted permission_model/subscription_model ARE loaded at runtime: a controller payload with an enum member the stale copy lacks (e.g. OPEN_DIAGNOSTIC) fails `ShardResponse` validation. `git grep -n "data_model.backend" -- shard_core tests` finds only the direct imports — check shard_model's own import block too.
- Exit code 0 = in sync, 1 = drift, 2 = setup error. Usable as a CI-style gate.

For the full multi-repo sync procedure and when to run `just get-types`, use **freeshard-ecosystem-contracts**.

## 2. Prove an env override lands — `verify-env-override.sh`

**What it measures:** shard_core settings use pydantic-settings with `env_prefix="FREESHARD_"` and `env_nested_delimiter="__"` (shard_core/settings.py). A nested var written with a SINGLE underscore is **silently ignored** — no warning, no error. This has shipped a production bug, and as of 2026-07-03 the justfile recipe `run-dev-for-freeshard-controller` still carries an inert var of this class — incident narrative and current status: freeshard-config-and-flags.

**Rule:** any time you add a `FREESHARD_*` var to docker-compose.yml, justfile, or CI, prove it lands:

```
.claude/skills/freeshard-diagnostics-and-tooling/scripts/verify-env-override.sh FREESHARD_DNS__ZONE=example.test dns.zone
```

**Expected output:**

```
PASS: FREESHARD_DNS__ZONE=example.test -> Settings().dns.zone == 'example.test'
```

and for the trap case:

```
$ .../verify-env-override.sh FREESHARD_DNS_ZONE=example.test dns.zone
FAIL: FREESHARD_DNS_ZONE=example.test was IGNORED -> Settings().dns.zone == 'localhost'
```

(the `localhost` comes from local_config.toml — the dev overlay wins when the env var doesn't parse as an override). Top-level scalars take a single level: `FREESHARD_PATH_ROOT_HOST=/srv/x path_root_host`. For the full option catalog and precedence rules, use **freeshard-config-and-flags**.

## 3. Find real code debt — `todo-scan.sh`

**What it measures:** actionable in-code markers. Two traps make naive scans lie here:

1. **All markers are lowercase** (`# todo:`). Scanners that grep `TODO|FIXME` (the common default) return **zero** hits in this repo.
2. Plain `grep -r` from repo root sweeps `.worktrees/` (stale agent worktrees → duplicate hits) and `data/eff_large_wordlist.txt` (`hacker` matches `hack`). The script uses `git grep -inI` (tracked text files only) and excludes `data/`, `tests/fixtures/`, `*.png`, `*.lock`.

**Expected output** (2026-07-03 — 5 real code todos, all in one subsystem, plus compose placeholders):

```
docker-compose.yml:38-42        #- AZURE_*=todo          <- self-hoster placeholders, not debt
shard_core/data_model/app_meta.py:48:# todo: use data_model.backend.shard_model.VmSize ...
shard_core/web/internal/app_error.py:45:# todo: add special splash screen for app that is not size compatible
shard_core/web/internal/call_peer.py:34:# todo: test this
tests/test_app_lifecycle.py:101:# todo: test_large_app_does_not_start
tests/test_app_lifecycle.py:103:# todo: test app with size comparison
```

**Interpretation:** four of the five real todos cluster in the app-size-compatibility subsystem (duplicate VMSize enum, missing size-incompatible splash, two missing size tests) — the repo's named code-debt hotspot; the fifth (call_peer.py:34 `todo: test this`) marks the untested `lru_cache`'d peer-proxy path (see freeshard-failure-archaeology §4.3). If your scan returns zero, your scanner is uppercase-only, not the repo clean.

## 4. Un-wedge the test suite — `test-db-cleanup.sh`

**What it fixes:** pytest (pytest-docker) starts postgres:17 under compose project `shard-core-test` with host port **5433 pinned** (tests/docker-compose.yml, tests/conftest.py `docker_compose_project_name`). Heavier `api_client` tests also create the Docker network `portal` and real app containers. A killed pytest leaves these behind; symptoms of leftovers:

| Symptom | Cause |
|---|---|
| `bind: address already in use` on 5433 at session start | stale `shard-core-test` postgres |
| `network with name portal already exists` / teardown hangs | stale `portal` network with containers still attached (incident: commit 28964fd "portal network not torn down between tests") |
| two worktrees' suites failing each other | both pin port 5433 + project name — suites cannot run concurrently on one host |

**Usage:** `.claude/skills/freeshard-diagnostics-and-tooling/scripts/test-db-cleanup.sh` — runs `docker compose -p shard-core-test -f tests/docker-compose.yml down -v --remove-orphans`, then removes the `portal` network **only if no containers are attached**. `--force` force-disconnects attached containers first (mirrors `tests/util.py:_force_remove_docker_network`). Do NOT `--force` while a dev shard (`just run-dev`) is using the `portal` network on the same host.

**Fast wiring check before/after:** `.venv/bin/pytest tests --collect-only -q` — imports every test module and the app package without starting Docker. Verified 2026-07-03: `134 tests collected in 0.29s` on the e55ce51 checkout (origin/main collects 137 — see freeshard-testing-and-qa). If collection fails, you have an import/syntax problem, not a Docker problem; fix that first. For fixture selection and flaky-test playbooks, use **freeshard-testing-and-qa**.

## 5. Where do bugs live — `churn-hotspots.sh`

**What it measures:** per-file commit counts (churn) and per-file *fix*-commit counts over git history. Naive `git log --name-only | sort | uniq -c` double-counts this repo because of two wholesale renames, which the script normalizes:

- `portal_core/` → `shard_core/` (commit 88e5842, 2025-02-11 — the project was formerly named "Portal")
- `shard_core/model/` → `shard_core/data_model/` (commit b5b4eda, 2025-08-04)

It also filters to files that still exist (`git ls-files`), so deleted files don't pollute the ranking.

**Usage:** full history, or `--since 2026-01-01` for the recent picture.

**Expected output shape** (real top entries, full history, 2026-07-03):

```
== top 20 by total churn ==
    107 tests/conftest.py
     69 shard_core/__init__.py
     45 shard_core/web/internal/auth.py
     38 shard_core/service/app_tools.py
== top 20 by fix-commit count ==
     33 tests/conftest.py
     15 shard_core/service/app_tools.py
     10 shard_core/app_factory.py
      9 shard_core/web/internal/auth.py
```

**Interpretation:** a file high on BOTH lists is a defect hotspot; expect hidden invariants and review scrutiny. Known hotspot families this confirms: the auth path (`web/internal/auth.py`, DB-pool exhaustion incident https://github.com/FreeshardBase/freeshard/issues/89), docker lifecycle (`service/app_tools.py`), and the proxy code (`web/internal/call_backend.py` / `call_peer.py` — repeat offender: Content-Type https://github.com/FreeshardBase/freeshard/issues/93, query strings, streaming). `shard_core/__init__.py` ranks high because version strings lived there historically — not a real hotspot. For the incident narratives, use **freeshard-failure-archaeology**.

## Measurement techniques (no script needed)

### fd headroom in a container (the EMFILE class)

```
docker exec traefik sh -c 'ulimit -n'
```

Container names on a shard are fixed by docker-compose.yml (`traefik`, `shard_core`, `postgres`, `web-terminal`). **Interpretation:** `1024` is the Docker per-container default soft limit; a Go binary built with Go < 1.19 does not self-raise RLIMIT_NOFILE, so 1024 is the whole budget for an internet-facing proxy — the June 2026 fleet outage ("up but not serving", `accept4: too many open files` in a hot loop) was exactly this, fixed by finite `readTimeout` (https://github.com/FreeshardBase/freeshard/pull/108) plus a fleet Traefik bump to a modern-Go build (decision comment on closed https://github.com/FreeshardBase/freeshard/pull/112: stay on Traefik v2, bump to v2.11 whose Go 1.25 self-raises nofile; note this repo's own docker-compose.yml — the self-hosted/dev stack — pins `traefik:v3.6` as of 2026-07-03). A value ≥ ~64000 means a modern Go runtime already self-raised it. Watch fd consumption live: `docker exec traefik sh -c 'ls /proc/1/fd | wc -l'` vs the ulimit.

### What a proxy ACTUALLY sends — tcpdump in the container's netns

When a request "should be fine" but the receiver rejects it, stop reasoning about what the code intends and capture the plaintext internal hop:

```
docker run --rm --net container:shard_core nicolaka/netshoot \
  tcpdump -i any -A -s0 'tcp port 80'
```

`--net container:<name>` joins the target's network namespace, so you see its traffic without touching the container. **Interpretation guide:** read the actual header block of the outbound request. This technique found that `call_backend` forwarded bodies but no `Content-Type` header — controller-inbound requests had Host, Content-Length, Content-Digest, Signature, but no Content-Type, so a strict FastAPI 422'd every proxied write while reads worked (https://github.com/FreeshardBase/freeshard/issues/93, root-cause in FreeshardBase/freeshard-controller#267). The red herring chased before capturing: double-encoding.

### OOM kill vs crash — SIGKILL(137) vs SIGABRT(134)

A restart-looping container "looks like OOM". Discriminate before buying RAM:

```
docker inspect <container> --format 'status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}}'
dmesg -T | grep -iE 'oom|killed process' | tail
```

| Evidence | Meaning |
|---|---|
| exit 137 (=128+9, SIGKILL) + `OOMKilled=true` or dmesg oom-kill lines | real memory exhaustion — resize / limit issue |
| exit 134 (=128+6, SIGABRT), `OOMKilled=false`, no dmesg oom entries | the process **aborted itself** — a crash/assert; more RAM changes nothing |
| exit 137, `OOMKilled=false`, but dmesg shows a *child* process oom-killed | cgroup OOM killed a child; the flag on the main container can stay false — trust dmesg |

Real precedent: a shard's Immich postgres restart-loop was assumed OOM (size-S shard); doubling RAM changed nothing because it was SIGABRT from a broken postgres extension. User-visibility of exactly this failure class is open work: https://github.com/FreeshardBase/freeshard/issues/120 and https://github.com/FreeshardBase/freeshard/issues/121.

### disk_space_low — what it actually means

`shard_core/service/disk.py`: a `PeriodicTask` runs `update_disk_space()` every 30 s (app_factory.py:134). It calls `shutil.disk_usage(settings().path_root / "user_data")` and sets `disk_space_low = free < 1 GiB` (disk.py:24-28, GiB = 1024³). Consequences of the flag: app starts are refused (service/app_lifecycle.py:26,55) and the app-error splash reports it (web/internal/app_error.py:59). Read it: `GET /protected/stats/disk` (externally `https://<shard-domain>/core/protected/stats/disk`), or the `disk_usage_update` websocket broadcast (service/websocket.py:114-116). Notes: it measures the **filesystem containing `{path_root}/user_data`**, not the whole disk; on a dev checkout `path_root` is `run/` (local_config.toml), so it measures your dev machine's disk; the module-level value starts as all-zeros/`False` until the first 30 s tick.

### Profiling — yappi (available, usage unproven)

`yappi` is a dev dependency (pyproject.toml `[project.optional-dependencies].dev`; import verified 2026-07-03). There is one opt-in fixture, `profile_with_yappi` (tests/conftest.py:398-403): wall-clock mode, wraps the test in `yappi.run()`, prints func stats after. As of 2026-07-03 **no test requests it** — treat it as a candidate tool, not an established practice. Use: add `profile_with_yappi` to a slow test's signature, run that single test, read the printed `tsub`/`ttot` columns (own time vs cumulative). Precedent for perf work here is the auth-path fix (https://github.com/FreeshardBase/freeshard/issues/89 → PR #90); nothing in the repo shows yappi was the tool used.

### GH issue/board queries that actually work (FreeshardBase specifics)

```
# Issue with comments — the --comments flag FAILS on this org:
gh issue view 24 --repo FreeshardBase/freeshard --json body,comments
# (gh issue view 24 --comments errors: "GraphQL: Projects (classic) is being
#  deprecated ... (repository.issue.projectCards)")

# Dev Board (org Projects v2: project 3 = Dev Board, project 2 = Roadmap):
gh project item-list 3 --owner FreeshardBase --format json --limit 200
```

Board item fields (verified 2026-07-03): `title`, `status`, `stage` (Backlog/Refined/Done), `priority` (P0–P3), `"needs Intent"`, `"blocked By"`, `"linked pull requests"`, `repository`, `content`, `assignees`, `labels` — gh omits fields that are empty on an item, so use `.["needs Intent"] // empty` style jq. **Substring-leak trap:** filtering by `.content.url | contains("FreeshardBase/freeshard")` also matches the 37 freeshard-controller items (2026-07-03: board had 71 items, only 25 from this repo). Filter exactly:

```
gh project item-list 3 --owner FreeshardBase --format json --limit 200 \
  --jq '.items[] | select(.repository=="https://github.com/FreeshardBase/freeshard") | "\(.priority // "-") \(.stage // "-") \(.title)"'
```

Also: labels are NOT the triage system here (only one custom label, `high-priority`); priority lives in the board fields. `--json stateReason` is not a valid issue field via gh.

### Production shards — the controller diagnostics API

You cannot SSH into or `docker exec` on a customer shard from here. The sanctioned path is the controller's **Shard Diagnostics** feature (merged as FreeshardBase/freeshard-controller#303, 2026-06-16): a human operator opens a time-boxed, read-only, **leveled** diagnostic on one shard (L1 system state → L2 +logs → L3 +data reads; promotion is up-only), and hands the diagnostic **id** to the agent. The agent then runs probes from a server-side allowlisted command catalogue via controller endpoints — an agent token is inert until an operator opens a diagnostic, and every probe/note lands in an append-only audit timeline. If you are asked to troubleshoot a production shard: request that an operator open a diagnostic and give you its id; without one there is by design nothing you can do. The API and probe catalogue live in the freeshard-controller repo, not here.

### Repo-native tooling worth knowing

- `scripts/generate_traefik_dyn_config_model.py` — the generator that once produced the 1117-line `shard_core/data_model/traefik_dyn_config.py` from the Traefik v2 JSON schema. It deliberately `raise`s on run ("Do no use! Output file was manually changed by adding authResponseHeadersRegex.") and still points at the pre-rename `portal_core/model/` path. Do not run it; edit the model by hand and keep the manual patch.
- `justfile` — check it before inventing commands: `just cleanup` (ruff --fix + black), `just run-dev`, `just get-types`, `just set-version X`.
- `management_mock.py` (repo root) — a mock of the management API for local dev; see **freeshard-build-and-env** / **freeshard-run-and-operate** for how it's used.

## When NOT to use this skill

- You have a **symptom** and want the known cause → **freeshard-debugging-playbook** (this skill gives you instruments; that one gives you diagnoses).
- You want the story/evidence of a past incident → **freeshard-failure-archaeology**.
- You're adding/altering a config option or need env-precedence semantics → **freeshard-config-and-flags** (this skill only *proves* an override lands).
- You're writing or fixing tests, choosing fixtures, or chasing flakes → **freeshard-testing-and-qa** (this skill only un-wedges hung test infra and checks collection).
- You need the cross-repo type-sync **procedure** or contract map → **freeshard-ecosystem-contracts** (this skill only *measures* drift).
- You're setting up a dev environment or worktree → **freeshard-build-and-env**.
- You're deciding whether a change may ship / how to release → **freeshard-change-control**.

## Provenance and maintenance

Written 2026-07-03 against freeshard main-lineage checkout (branch fix-profile-billing-fields, HEAD e55ce51). Primary sources: the repo itself (shard_core/settings.py, shard_core/service/disk.py, tests/conftest.py, tests/util.py, justfile, pyproject.toml, docker-compose.yml), GitHub issues/PRs cited inline (freeshard #89 #93 #108 #111 #112 #120 #121; freeshard-controller #267 #303), and commits 5de2998, 88e5842, b5b4eda, 6d4b101, e55ce51, 28964fd. All five scripts executed 2026-07-03 except test-db-cleanup.sh (mutating; syntax-checked, component reads tested).

Drift-prone facts — re-verify before relying:

| Fact (as of 2026-07-03) | Re-verification command |
|---|---|
| Backend type copy drift state (diagnostic_model missing, 3 files drifted) | `.claude/skills/freeshard-diagnostics-and-tooling/scripts/check-type-drift.sh` |
| shard_core imports backend copy in 4 modules + tests (plus shard_model's transitive imports) | `git grep -n "data_model.backend" -- shard_core tests` and `head -12 shard_core/data_model/backend/shard_model.py` |
| 5 lowercase code todos, all in app-size subsystem | `.claude/skills/freeshard-diagnostics-and-tooling/scripts/todo-scan.sh` |
| 134 tests collected at e55ce51 (137 on origin/main), collection needs no Docker | `.venv/bin/pytest tests --collect-only -q` |
| Test compose project `shard-core-test`, host port 5433 | `grep -n "shard-core-test" tests/conftest.py; grep -n 5433 tests/docker-compose.yml` |
| disk_space_low threshold = free < 1 GiB on user_data, 30 s period | `sed -n '22,30p' shard_core/service/disk.py; grep -n update_disk_space shard_core/app_factory.py` |
| yappi fixture exists but no test uses it | `git grep -n profile_with_yappi -- tests` |
| Dev Board = project 3, 25/71 items from this repo, field names | `gh project item-list 3 --owner FreeshardBase --format json --limit 200 --jq '[.items[] \| keys] \| add \| unique'` |
| `gh issue view --comments` still broken on this org | `gh issue view 24 --repo FreeshardBase/freeshard --comments` (expect projectCards GraphQL error) |
| Diagnostics feature shape (levels, operator-gated) | `gh pr view 303 --repo FreeshardBase/freeshard-controller --json body` |
| Fixed container names traefik/shard_core/postgres/web-terminal | `grep -n container_name docker-compose.yml` |
