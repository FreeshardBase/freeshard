---
name: freeshard-debugging-playbook
description: Symptom-to-triage playbook for known Freeshard shard_core failure modes. Use when diagnosing a live or reported failure: shard up but unreachable, "too many open files" in traefik logs, all controller writes return 422, app won't start / container name conflict / stale network, backup failures or rclone errors, burst 500s on app access, Immich thumbnails broken or postgres crash-looping, app stuck INSTALLATION_QUEUED, config override silently ignored, OOM kills / restart loops. TRIGGER on incident reports, "shard unreachable", "backups failing", "app stuck", error strings like EMFILE, 422 Unprocessable, "already in use", PANIC, SIGABRT. SKIP when writing new tests or diagnosing test flakiness (use freeshard-testing-and-qa), when you need measurement tooling (use freeshard-diagnostics-and-tooling), or when researching WHY the design is this way (use freeshard-architecture-contract or freeshard-failure-archaeology).
---

# Freeshard Debugging Playbook

Symptom → discriminating experiment → fix, for every failure mode this project has already paid to learn. Written 2026-07-03. Verify volatile facts (issue states, versions) before acting on them — re-verification commands are in the last section.

**Terms** (used throughout, defined once):

| Term | Meaning |
|---|---|
| shard | A customer VM running the shard_core stack: `postgres:17`, `traefik`, `shard_core` (this repo's image), `web-terminal`, plus one Docker Compose project per installed app — all on one Docker network named `portal` (docker-compose.yml). |
| controller | freeshard-controller, the central cloud service at controller.freeshard.net. Provisions shards, issues backup SAS URLs, receives telemetry. |
| forwardAuth | Traefik middleware: every request to an app subdomain is first sent to shard_core `GET /internal/auth`; a 200 lets the request through. Auth is enforced by Traefik, NOT inside FastAPI routes. |
| hosted vs self-hosted | Same image and compose file. Hosted shards are known to the controller (profile, backups, management API work); self-hosted shards get profile=None and no backups. |
| merged ≠ shipped | A fix on `main` reaches no shard until a version bump + GitHub Release + controller core-version rollout. See freeshard-change-control. Evidence: [#111](https://github.com/FreeshardBase/freeshard/issues/111). |

## First 15 minutes on any incident

Access note: on hosted customer shards there is no ad-hoc SSH; probes run through the controller's operator-activated diagnostics API. Locally (dev compose stack) run these directly.

```bash
# 1. What is running, what is restarting, what is unhealthy?
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.RestartCount}}'

# 2. Is shard_core itself alive? (healthcheck endpoint, same one the Dockerfile uses)
docker exec shard_core curl -sf http://localhost/public/health   # expect {"status":"ok"}
# From outside, through traefik: curl -sf https://<domain>/core/public/health

# 3. Disk. Two known incidents were "really a full disk" (log spam, backups).
df -h /   # shard_core also stops ALL apps when free space on user_data < 1 GiB (shard_core/service/disk.py:28)

# 4. Logs, most recent first. shard_core logs to stdout.
docker logs --tail 300 shard_core
docker logs --tail 300 traefik      # look for "too many open files", ACME errors
docker logs --tail 100 <app-container>

# 5. App status as the DB sees it (statuses: INSTALLATION_QUEUED, INSTALLING,
#    STOPPED, RUNNING, DOWN, ERROR, ... — shard_core/data_model/app_meta.py:29)
docker exec -it postgres psql -U shard_core -c "select name, status from installed_apps;"
```

Then match the symptom against this table.

## Symptom → triage index

| # | Symptom | First discriminator | Likely cause |
|---|---|---|---|
| 1 | Shard containers all "Up", but nothing reachable from outside | `docker exec traefik sh -c 'ulimit -n'` + traefik log grep "too many open files" | Traefik fd exhaustion |
| 2 | Every WRITE to the controller (via shard proxy) returns 422; reads fine | tcpdump the internal hop: is Content-Type present? | Proxy dropped Content-Type |
| 3 | One app won't start; logs say name "already in use" or network "not found" | `docker logs shard_core` grep for auto-recovery warnings | Stale Docker state after core update |
| 4 | Backups failing / no recent backup marker | rclone exit + last stderr line; does the flag exist in the shipped rclone? | rclone flag/output-parsing class |
| 5 | Burst of 500s when opening an app (esp. SPA firing many parallel requests) | pool wait timeouts in shard_core logs; were auth caches invalidated? | forwardAuth DB-pool exhaustion (regression of #89) |
| 6 | Immich thumbnails broken / uploads fail / its postgres crash-looping | THREE distinct modes — discriminate before acting (see §6) | pgvecto.rs corruption vs VectorChord stale index vs upstream regression |
| 7 | App randomly dies / restarts; user sees bare 502 | `docker inspect` OOMKilled + RestartCount | OOM kill or idle-stop mid-migration (open #120/#121) |
| 8 | A config/env override silently does nothing | one-liner Settings() probe (see §8) | Single-underscore env var name |
| 9 | Test passes locally, times out only in CI | — | Known flaky class → freeshard-testing-and-qa |
| 10 | App stuck in INSTALLATION_QUEUED or INSTALLING forever (esp. after restart) | Was shard_core restarted since the install was queued? | In-memory queue, no startup reconciliation |

---

## 1. Shard "up but unreachable" — Traefik fd exhaustion

**Symptom.** All containers show "Up", shard_core health is green, but HTTP/HTTPS from outside hangs or is refused. Traefik log is a hot loop of `accept4: too many open files` (EMFILE). Bonus damage: that log loop itself can fill the root disk (a 38 GB traefik JSON log in 3 days was part of the June 2026 incident) — check `df -h` too.

**Discriminating experiment.**

```bash
docker exec traefik sh -c 'ulimit -n'
# ~1024        -> fd ceiling is the problem (old Go binary + low docker nofile default)
# ~64000+      -> ceiling fine; look elsewhere (DNS, certs, routing)

docker logs --tail 200 traefik 2>&1 | grep -c 'too many open files'
# >0 -> confirmed EMFILE; 0 -> not this failure mode
```

**Root cause (June 2026 incident).** Two factors multiplied: (a) Traefik with `readTimeout=0` leaks one fd per abandoned connection from internet scanners; (b) the hosted fleet's pinned Traefik v2.6 is built with a pre-1.19 Go (measured go1.17.10 — see freeshard-proof-and-analysis-toolkit Recipe 1), which does not self-raise `RLIMIT_NOFILE` (Go 1.19+ does), so on newer Ubuntu base images with a 1024 per-container nofile soft limit the ceiling was hit within days. Older shards survived the identical leak only because their limit was higher — "old shards are fine" was luck, not health.

**Fix.** Both halves shipped: finite `readTimeout: 300s` on http/https entrypoints in the shard-generated static config (commit fd1d05b, PR [#108](https://github.com/FreeshardBase/freeshard/pull/108), released in 0.39.4), and the hosted fleet's Traefik bumped to v2.11 (Go 1.25, self-raises nofile) — the deliberate decision to stay on v2 rather than migrate to v3 is recorded in closed PR [#112](https://github.com/FreeshardBase/freeshard/pull/112)'s comment; v3 migration is a P3 backlog item. Note the hosted-fleet Traefik pin lives in freeshard-controller's core files, NOT in this repo; this repo's docker-compose.yml (self-hosted stack) pins `traefik:v3.6` (as of 2026-07-03, docker-compose.yml:29).

**If you hit it anyway:** restart traefik for immediate relief, then verify `readTimeout` is present in `/core/traefik.yml` on the shard (it comes from `data/traefik.yml` in this repo) and check the shard's core version is ≥ 0.39.4. This is a "merged-but-not-rolled-out" trap — the fix sat unreleased once already ([#111](https://github.com/FreeshardBase/freeshard/issues/111)).

## 2. All controller writes 422, reads fine — proxy dropped Content-Type

**Symptom.** Every POST/PUT proxied from the terminal through shard_core's `/internal/call_backend/...` to the controller returns 422 Unprocessable Entity; every GET works.

**Story.** shard_core's sign-and-forward proxy relayed the body but not the `Content-Type` header — harmless for years, until a controller-side FastAPI upgrade (0.115 → 0.136) started rejecting JSON bodies without a JSON Content-Type. Python `requests` sets no Content-Type for `data=<bytes>`. Issue [#93](https://github.com/FreeshardBase/freeshard/issues/93), fixed in PR [#94](https://github.com/FreeshardBase/freeshard/pull/94); the fix and its rationale are commented in `shard_core/web/internal/call_backend.py:30-40`. A red herring (double-encoding) was chased first.

**Discriminating experiment.** Traefik swallows the detail; look at the actual bytes on the plaintext internal hop with a netshoot sidecar in the target container's network namespace:

```bash
docker run --rm --net container:shard_core nicolaka/netshoot \
  tcpdump -i any -A -s0 'tcp port 80'
# Reproduce one failing write, then read the captured request:
#   Content-Type header present  -> not this bug; inspect the 422 response body for the real validation error
#   Content-Type header absent   -> this bug (or a regression of it)
```

**Fix/escalation.** Ensure the proxy forwards Content-Type (call_backend.py already does; check any NEW proxy path). General rule for any sign-and-forward proxy in this codebase: forward semantically load-bearing headers with the body. Related repeat offenders in the same file family: query strings (#19), streaming instead of buffering (#38/#39).

## 3. App won't start — stale Docker state (name conflict / dead network)

**Symptom.** An app fails to start after a core update or host reboot. `docker logs shard_core` (or the SubprocessError) contains either `Conflict... already in use` (container name) or `network ... not found`.

**Story.** Docker objects (containers, networks) survive core updates and go stale. Fixed three times: [#63](https://github.com/FreeshardBase/freeshard/issues/63) (name conflicts, commit fefd2f4), root cause of stale containers on core update (751678d), and stale network references ([#54](https://github.com/FreeshardBase/freeshard/issues/54), d66d889).

**Current behavior.** `docker_start_app` auto-recovers from both modes by string-matching the error text and running `compose down` + `up -d` (`shard_core/service/app_tools.py:43-61`). This is fragile by design — if Docker changes its error messages, recovery silently stops matching.

**Discriminating experiment.**

```bash
docker logs shard_core 2>&1 | grep -E 'stale (network reference|containers) for app'
# Hit  -> auto-recovery fired; if the app STILL fails, the staleness is a new, unmatched variant
# Miss -> not the known staleness class; read the raw compose error
```

**Fix/escalation.** Manual recovery: `docker compose down && docker compose up -d` with cwd `<path_root>/core/installed_apps/<app>/`. If you found a NEW staleness variant, extend the string-match in app_tools.py (plus its tests) rather than adding a separate ad-hoc retry path. Also note `docker_start_app` is `@throttle(5)` — global across ALL apps, silently dropping calls within 5s of any other app's start (`shard_core/util/misc.py`); a "second app didn't start" report right after another app started may just be the throttle.

## 4. Backup failures — the rclone class

Backups: daily CronTask 03:00 UTC + ≤1h jitter runs `rclone ... sync` of `core/` and `user_data/` to an Azure blob container via a controller-issued SAS URL, crypt-encrypted with a passphrase from the `kv_store` table (`shard_core/service/backup.py`). Four distinct known failure modes:

**(a) Flag not supported by the shipped rclone.** [#117](https://github.com/FreeshardBase/freeshard/issues/117) (P0 release blocker): ALL v18 backups failed because `--azureblob-no-check-container`, added in the cost optimization PR [#106](https://github.com/FreeshardBase/freeshard/pull/106), did not exist in the rclone version baked into the image (Dockerfile installs rclone from Debian bookworm). Fixed by dropping the flag, PR [#119](https://github.com/FreeshardBase/freeshard/pull/119). **Rule: any new rclone flag must be validated against the image's pinned rclone version** — `docker run --rm ghcr.io/freeshardbase/freeshard:<tag> rclone help flags | grep <flag>`.

**(b) Strict parsing of rclone's stats JSON.** Recurred across two years: 9666db5 (2024, 0.28.x rollout) and b9dfcfd (2026, 0.38.3). **Rule: rclone's JSON log/stats output is an opaque dict; never pydantic-validate its shape.**

**(c) Dead cron task.** CronTask used to die permanently on any exception, silently killing all future backups until restart ([#58](https://github.com/FreeshardBase/freeshard/issues/58)). Fixed: both PeriodicTask and CronTask now catch, log, and keep looping (`shard_core/util/async_util.py:98-101`). If backups stopped and there's no error at 03:00-ish in the logs, suspect this class regressed.

**(d) Exit-code masking.** Historically `_backup_directory` never checked the rclone returncode — an rclone failure whose last stderr line happened to be valid JSON was recorded as a successful backup, and real failures surfaced as confusing `JSONDecodeError`s. Fixed on main (a4a80bc, merged 2026-06-30 via PR #119: `process.returncode != 0` now raises `BackupFailedError`, backup.py:177-180) — **but as of 2026-07-03 that commit is in no released tag** (`git tag --contains a4a80bc` is empty). Deployed shards ≤ 0.39.4 still have the masking behavior.

**Discriminating experiment.**

```bash
docker logs shard_core 2>&1 | grep -iE 'rclone|backup' | tail -30
# "Error: unknown flag"            -> mode (a): flag vs pinned rclone version
# "Failed to parse rclone output"  -> mode (b) or, on <=0.39.4, a masked real failure (d)
# nothing at all around 03:00 UTC  -> mode (c) or the task never started; check task startup logs
```

Recency check without logs: the `_last_backup` marker blob's Last-Modified in the Azure container is the controller's recency signal (backup.py:133-151); a `backups` table row is written per run (`select * from backups order by 1 desc limit 3;`).

Self-hosted note: backups REQUIRE a controller SAS URL — on self-hosted shards `start_backup` always fails with `BackupStartFailedError`. Not a bug.

## 5. Burst 500s on app access — forwardAuth pool exhaustion

**Symptom.** Opening an app (especially an SPA that fires ~30 parallel requests, e.g. Actual Budget) yields a batch of 500s; single requests fine.

**Story.** forwardAuth means EVERY app request hits shard_core `/internal/auth`. It used to cost 2-3 DB queries per call; a 4-connection pool exhausted under SPA bursts → 30s pool waits → 500s. Issue [#89](https://github.com/FreeshardBase/freeshard/issues/89) (high-priority), fixed in PR [#90](https://github.com/FreeshardBase/freeshard/pull/90): pool `max_size=20, timeout=10` (`shard_core/database/connection.py:28-29`) plus in-process `_identity_cache`/`_app_cache` making the auth path zero-DB at steady state. Caches have NO TTL — they are invalidated only by the `on_identity_update` / `on_apps_update` signals (`shard_core/web/internal/auth.py:36-44`).

**Discriminating experiment.** If burst 500s reappear, the prime suspect is a cache-invalidation gap, not pool size:

```bash
# Did some code path change identity/app state WITHOUT emitting the signal?
git grep -n "send_async" shard_core | grep -E "on_apps_update|on_identity_update"
# Cross-check: every writer of installed_apps/identities rows must appear here.
# Meanwhile in logs: psycopg pool timeout errors around the burst -> pool path; auth 401/500 with fresh state -> stale cache.
```

**Rule.** Any NEW per-request lookup added to the auth path needs a cache with signal-driven invalidation, or it recreates #89. Every DB status change must be followed by `await signals.on_apps_update.send_async()` — forgetting it means stale auth decisions until the next unrelated update.

## 6. Immich broken — THREE distinct failure modes. Discriminate first.

Immich incidents get conflated because all three end in "thumbnails/uploads broken". Acting on the wrong one wastes hours (e.g. doubling RAM for a non-OOM crash). Details below are from the June/July 2026 production incidents; recovery specifics are operational knowledge, not verifiable in this repo — re-check against current Immich/VectorChord docs before running them.

| Mode | Fingerprint | NOT this if... |
|---|---|---|
| (A) pgvecto.rs index corruption | Immich's postgres container crash-loops on a ~86s period; its logs show `PANIC` with `ERRORDATA_STACK_SIZE` (signal 6); thumbnails 404 | postgres stays up |
| (B) VectorChord 0.3→0.4 stale index | Uploads/jobs abort; postgres process dies with **SIGABRT, not SIGKILL** — doubling RAM changes nothing (that is the discriminator vs OOM); happens after an Immich upgrade needing VectorChord 0.4.x while the packaged postgres image ships 0.3.0 | `dmesg`/`docker inspect` shows OOMKilled=true (then it's §7) |
| (C) Upstream v2.7.x aspect-ratio regression | Thumbnails wrong/broken but DB perfectly healthy, no crashes | any postgres crash present |

**Discriminating experiment.**

```bash
docker inspect --format 'OOM={{.State.OOMKilled}} Exit={{.State.ExitCode}} Restarts={{.RestartCount}}' <immich-postgres-container>
docker logs --tail 200 <immich-postgres-container> 2>&1 | grep -E 'PANIC|SIGABRT|vchord|vectors'
# PANIC + crash loop            -> mode A
# SIGABRT on REINDEX/insert     -> mode B
# clean logs, OOM=false         -> mode C (upstream; check Immich version against upstream changelog)
```

**Recovery sketches.** A: clear the pg_vectors index data and migrate to VectorChord. B (July 2026, recovered with no data loss): create the missing `pg_vectors/indexes` dir, `ALTER EXTENSION vchord UPDATE`, then `REINDEX`. C: wait for/pin an upstream fix; nothing shard-side to do.

**Systemic fixes filed** (open as of 2026-07-03): derive app compose from upstream's version-pinned compose so supporting-image versions can't drift ([app-repository#29](https://github.com/FreeshardBase/app-repository/issues/29)); don't let the lifecycle manager kill in-flight migrations ([#121](https://github.com/FreeshardBase/freeshard/issues/121)); show "updating" instead of a bare 502 ([#120](https://github.com/FreeshardBase/freeshard/issues/120)).

## 7. OOM kills / restart loops invisible to the user

**Symptom.** User reports an app "sometimes doesn't work" or shows a bare 502; nothing in the UI explains why. On size-S shards (2 CPU/4GB) heavyweight apps (Immich) get OOM-killed and restart-loop silently. Open issue: [#120](https://github.com/FreeshardBase/freeshard/issues/120).

**Adjacent trap:** shard_core's idle-stop (apps stopped after `idle_time_for_shutdown`, default 60s, when no authed request arrives) can kill an app mid-database-migration right after an update — the app is "busy", not "idle", but shard_core only counts inbound requests. Open issue: [#121](https://github.com/FreeshardBase/freeshard/issues/121). Also note: idle-stop's last-access state is in-memory only, so after a shard_core restart ALL non-always-on running apps get stopped on the first `control_apps` tick (`shard_core/service/app_lifecycle.py:63-66` area) — a wave of app stops right after a core update is expected behavior, not an incident.

**Discriminating experiment.**

```bash
docker inspect --format 'OOM={{.State.OOMKilled}} Exit={{.State.ExitCode}} Restarts={{.RestartCount}}' <app-container>
# OOM=true                    -> genuine OOM: app vs VM size; check app's minimum_portal_size vs shard vm_size
# OOM=false, app was stopped  -> check shard_core logs for idle-stop ("stopping app") near the failure time
```

**Escalation.** Both are open product gaps, not code bugs you should hotfix ad hoc — if your task touches them, work the issues, don't invent a side-channel fix.

## 8. Config override silently not applying

**Symptom.** You set an env var (compose file, .env, CI) and shard_core behaves as if it isn't there. No error anywhere.

**Story.** Settings use pydantic-settings with `env_prefix="FREESHARD_"` and `env_nested_delimiter="__"` (`shard_core/settings.py:111-112`). A nested field needs a DOUBLE underscore between section and field: `FREESHARD_DNS__ZONE`, not `FREESHARD_DNS_ZONE`. Single-underscore names are silently ignored and the TOML value wins. This has shipped as a real production bug before — incident narrative and the still-broken justfile recipe: freeshard-config-and-flags.

**Discriminating experiment** (run in repo root, needs `uv sync`; prints the dev-config fallback `localhost` when the var is ignored):

```bash
FREESHARD_DNS__ZONE=probe.example .venv/bin/python -c \
  "from shard_core.settings import Settings; print(Settings().dns.zone)"   # -> probe.example
FREESHARD_DNS_ZONE=probe.example .venv/bin/python -c \
  "from shard_core.settings import Settings; print(Settings().dns.zone)"   # -> localhost (silently ignored)
```

Adapt the field path to whatever you're overriding. Precedence: env > `local_config.toml` > `config.toml`. Also: the `CONFIG` env var seen in the justfile and CI is dead — nothing reads it. Full catalog: freeshard-config-and-flags.

## 9. Test fails only in CI (timeout)

Known flaky class with documented precedent fixes (timeout bumps, LifespanManager shutdown_timeout, network teardown, demote-to-unit-test). Do not debug from scratch here — go to **freeshard-testing-and-qa**.

## 10. App stuck INSTALLATION_QUEUED / INSTALLING after a restart

**Symptom.** An app shows INSTALLATION_QUEUED or INSTALLING indefinitely; nothing is happening.

**Root cause.** The installation queue is a single in-memory `asyncio.Queue` drained by one serial worker (`shard_core/service/app_installation/worker.py`). It is NOT persistent and there is NO startup reconciliation: if shard_core restarts between enqueue and completion, the DB row is stranded in its transitional status forever. Apps in INSTALLATION_QUEUED/INSTALLING are also excluded from lifecycle control (`app_lifecycle.py:45`) and from traefik routing, so the app is fully inert. Additional stall cause without a restart: the zip download has no timeout, so a hung app store stalls the whole serial worker (worker is one-at-a-time — one stuck install blocks ALL queued installs).

**Discriminating experiment.**

```bash
# Was shard_core restarted after the install was queued?
docker inspect --format '{{.State.StartedAt}}' shard_core
docker exec -it postgres psql -U shard_core -c \
  "select name, status from installed_apps where status like '%QUEUED%' or status like '%INSTALLING%';"
# Rows older than the container start -> stranded; no restart -> check whether the worker is stuck on a download (thread dump / logs)
```

**Recovery.** Two safe paths, both via the terminal-authed API (or the DB as last resort):
- Uninstall: `DELETE /protected/apps/{name}` — `_uninstall_app` deliberately asserts NO status precondition (worker.py:124-134), so it works from any stranded state. Then reinstall fresh.
- Reinstall in place: `POST /protected/apps/{name}/reinstall` — reinstall is also allowed from any status (`app_installation/__init__.py:91`).

Caveat: uninstall swallows shutdown errors and proceeds to delete files + DB row — if containers existed and `compose down` failed, orphaned containers/networks remain; sweep with `docker ps -a` afterwards.

---

## Cross-cutting traps (read once, save hours)

- **Merged is not shipped.** Check `git tag --contains <sha>` before assuming a fix is on any shard. Two incidents (#111, the backup returncode fix) sat merged-but-unreleased. Release gates: freeshard-change-control.
- **The local checkout lies.** Always `git fetch` and reason from `origin/main`; this repo's worktrees and branches are often behind or divergent.
- **Traefik swallows error detail.** For anything on the internal plaintext hop, tcpdump via `docker run --rm --net container:<name> nicolaka/netshoot tcpdump -i any -A -s0 'tcp port 80'`.
- **"Up" is not "serving".** A container can be Up while its process is EMFILE-looping (§1) or its web entrypoint 200s before the backend is ready (split web/backend apps).
- **Signals discipline.** Sync-emitted blinker signals must have sync receivers; `send_async` for async ones. An async receiver on a sync signal is a silently un-awaited coroutine.
- **Auth on the docker network is absent by design.** All auth is Traefik forwardAuth; `docker exec`/on-network curl bypasses it. Never conclude "auth is broken" from an on-network probe, and never publish shard_core's port.
- **ERROR status has no persisted reason.** `update_app_status(..., message=...)` only logs the message; after a UI reload an ERROR app shows no cause. Get the reason from shard_core logs at failure time.

## When NOT to use this skill

- Designing/adding tests, or a test is flaky → **freeshard-testing-and-qa**.
- You need to measure (profiling, counting queries, load) rather than pattern-match a known symptom → **freeshard-diagnostics-and-tooling**.
- You want the full history of an investigation, its dead ends and rejected fixes → **freeshard-failure-archaeology**.
- You're deciding whether/how a fix may ship, or classifying a change → **freeshard-change-control**.
- The problem is env setup (uv, worktrees, type-sync) → **freeshard-build-and-env**; running/deploying the stack → **freeshard-run-and-operate**.
- You need theory (crypto, HTTP signatures, forwardAuth mechanics, rclone crypt) → **freeshard-domain-reference**.
- Config axes and every override rule in detail → **freeshard-config-and-flags**.

## Provenance and maintenance

Written 2026-07-03 against origin/main tip 0a40684 (local checkout: branch fix-profile-billing-fields, 0.39.2). Primary sources: this repo's code and git history; GitHub issues/PRs cited inline (FreeshardBase/freeshard #54 #58 #63 #89 #90 #93 #94 #106 #108 #111 #112 #117 #119 #120 #121; app-repository#29); commits fd1d05b, 5de2998, a4a80bc, 9666db5, b9dfcfd, fefd2f4, d66d889, 1e0e7c1. Immich recovery specifics (§6) come from June/July 2026 production incident operations and are not verifiable in this repo — treat as leads, not gospel.

Drift-prone facts — re-verify before relying on them:

| Fact (as of 2026-07-03) | Re-verify with |
|---|---|
| Backup returncode fix (a4a80bc) in no released tag | `git fetch && git tag --contains a4a80bc` |
| Latest release 0.39.4; local compose pins 0.39.x | `git ls-remote --tags origin \| tail -5` and `git show origin/main:docker-compose.yml \| grep image:` |
| Self-hosted compose pins traefik:v3.6; hosted fleet on v2.11 (controller-managed) | compose: same command as above; fleet pin lives in freeshard-controller core files — check there |
| Issues #120, #121, #91, app-repo#29 still OPEN | `gh issue view <n> --repo FreeshardBase/freeshard --json state` |
| Auth caches + signal invalidation unchanged | `grep -n "_invalidate" shard_core/web/internal/auth.py` |
| Pool max_size=20, timeout=10 | `grep -n max_size shard_core/database/connection.py` |
| Docker staleness auto-recovery string-matches unchanged | `sed -n '40,65p' shard_core/service/app_tools.py` |
| rclone flags in COMMAND_TEMPLATE (currently `--fast-list`, no `--azureblob-no-check-container`) | `git show origin/main:shard_core/service/backup.py \| sed -n '32,48p'` |
| Env delimiter `__`, prefix FREESHARD_ | `grep -n env_nested_delimiter shard_core/settings.py` |
| No startup reconciliation of queued statuses | `grep -rn "QUEUED" shard_core/app_factory.py` (expect no hits) |
| Health endpoint /public/health | `grep -rn 'prefix="/health"' shard_core/web/public/health.py` |
| readTimeout 300s in traefik static template | `git fetch && git show origin/main:data/traefik.yml \| grep -n readTimeout` (the local checkout can predate the fix) |
