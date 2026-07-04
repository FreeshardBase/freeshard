---
name: freeshard-failure-archaeology
description: Chronicle of every major Freeshard incident, dead-end branch, rejected fix, and revert — so you never re-fight a settled battle. TRIGGER when starting work that touches backup/rclone, TinyDB/Postgres/storage, Docker lifecycle (stale containers/networks, python-on-whales), Traefik/proxy/call_backend, splash screens, releases/CI, or when you wonder "has this been tried before?", "why is this code weird?", "why is this PR/branch abandoned?". Also TRIGGER before resurrecting any unmerged branch or closed PR. SKIP when you need live-symptom triage steps (use freeshard-debugging-playbook), design rationale for current architecture (use freeshard-architecture-contract), or release/merge procedure (use freeshard-change-control).
---

# Freeshard Failure Archaeology

This is the incident chronicle for shard_core (this repo, `shard_core/` — the per-VM FastAPI service that manages Docker apps behind Traefik on a "shard", a customer's personal cloud VM). It records what broke, why, and what was decided, so a fresh session does not re-attempt a dead end or undo a settled decision.

Terms used throughout:

- **controller** = [FreeshardBase/freeshard-controller](https://github.com/FreeshardBase/freeshard-controller), the central service that provisions shard VMs and delivers **core versions** (v1…v18: per-shard bundles of docker-compose.yml + host migration scripts). Production shards run what the core version pins, NOT what this repo's `docker-compose.yml` says.
- **call_backend / call_peer** = shard_core's sign-and-forward HTTP proxies (`shard_core/web/protected/`, `shard_core/web/internal/call_peer.py`) that relay requests to the controller / other shards with HTTP-signature auth.
- **grind** = the overnight agent loop: one headless AI session per GitHub issue, own worktree, branch from main, PR for human review. Nothing auto-merges.

Entry format: **SYMPTOM → ROOT CAUSE → EVIDENCE → STATUS**. All issue/PR numbers without a repo prefix are in FreeshardBase/freeshard. Dates of volatile facts are as of 2026-07-03.

---

## 1. Backup / rclone pipeline

The single most incident-dense subsystem. Read this whole section before touching `shard_core/service/backup.py`.

### 1.1 rclone rollout incident chain, 0.28.0–0.28.6 (seven releases in three days, 2024-04-20..22)

- SYMPTOM: auto-backup feature shipped in 0.28.0; production backups failed repeatedly, each fix revealing the next failure.
- ROOT CAUSE (serial): Docker image shipped without the rclone binary; then rclone's multi-line output broke parsing; then strict Pydantic validation of rclone's log JSON broke on missing fields; then a wrong SAS-token path.
- EVIDENCE: commits `cba5806` "install rclone to docker image", `2d2ec22` "use last line of rclone output", `9666db5` "make all rclone log fields optional", `b4c5eda` "Use new backup sas token path"; tags 0.28.0 (2024-04-20) through 0.28.6 (2024-04-22).
- STATUS: fixed by 0.28.6, but the parsing class of bug **recurred** — see 1.2.

### 1.2 rclone-output validation recurrence (2026) — the opaque-dict rule

- SYMPTOM: backups failed validation again two years later, right after the Postgres release.
- ROOT CAUSE: same class as `9666db5` (2024): Pydantic-validating rclone's stats JSON, whose shape is not a stable contract.
- EVIDENCE: commit `b9dfcfd` "treat rclone stats as opaque dict to prevent backup validation failures" (released 0.38.3, 2026-04-18).
- STATUS: fixed. **Standing rule: never Pydantic-validate rclone stats/log output — treat it as an opaque dict.** It changed shape twice; assume it will again.

### 1.3 The 0.37.5 backport anomaly — tag order ≠ commit topology

- SYMPTOM (for archaeologists): tag 0.37.5 (2026-04-18) is *newer in time* than 0.38.0 (2026-04-17).
- ROOT CAUSE: the freshly released 0.38 Postgres line was evidently not trusted for immediate fleet rollout, so the rclone-stats fix was cherry-picked (`0a5f249`) onto branch `origin/release/0.37.5` (`3392ff3`) and shipped on the old TinyDB line too.
- STATUS: historical fact. **Never assume tag order equals commit topology in this repo.** Resolve with `git branch -a --contains <tag>`.

### 1.4 CronTask silent death kills backups permanently

- SYMPTOM: scheduled backups stopped forever with no error surfaced; only a restart revived them.
- ROOT CAUSE: `CronTask` background scheduler died on the first uncaught exception and never rescheduled.
- EVIDENCE: issue [#58](https://github.com/FreeshardBase/freeshard/issues/58), fixed in PR [#61](https://github.com/FreeshardBase/freeshard/pull/61) (merged 2026-04-14).
- STATUS: fixed. Rule: any background/periodic task must catch and log exceptions, or it dies silently and permanently.

### 1.5 No external backup-recency signal → marker blob

- SYMPTOM: the controller could not tell whether a shard's backups were actually running (see 1.4 for why that mattered).
- FIX: write a marker blob after each successful backup; the controller polls it.
- EVIDENCE: issue [#59](https://github.com/FreeshardBase/freeshard/issues/59), PR [#62](https://github.com/FreeshardBase/freeshard/pull/62) (merged 2026-04-14).
- STATUS: fixed. Any change to backup flow must keep the marker-blob write.

### 1.6 datetime in JSONB

- SYMPTOM: post-Postgres backups broke on serializing the directories structure.
- ROOT CAUSE: `datetime` objects are not JSON-serializable when writing JSONB columns.
- EVIDENCE: PR [#74](https://github.com/FreeshardBase/freeshard/pull/74) "fix(backup): serialize datetime in directories JSONB" (commit `935250b`, released 0.38.4).
- STATUS: fixed. Explicitly serialize datetimes before they hit JSONB.

### 1.7 Azure list-ops cost fix → v18 release-blocker regression

- SYMPTOM (first): Azure "List and Create Container Operations" meter cost several times the actual stored backup data.
- FIX (first): add `--fast-list` and `--azureblob-no-check-container` to the rclone sync, PR [#106](https://github.com/FreeshardBase/freeshard/pull/106) (merged 2026-06-13).
- SYMPTOM (second): **all** backups on core v18 failed — the rclone binary pinned in the shipped image did not know `--azureblob-no-check-container`.
- EVIDENCE: release-blocker issue [#117](https://github.com/FreeshardBase/freeshard/issues/117), fixed by PR [#119](https://github.com/FreeshardBase/freeshard/pull/119) dropping the unsupported flag (2026-06-30).
- STATUS: fixed. **Rule: any new rclone flag must be validated against the rclone version pinned in the Docker image before merge.**

Also in this subsystem: empty directories were silently lost by backup/restore — fixed in PR [#52](https://github.com/FreeshardBase/freeshard/pull/52).

---

## 2. Database: three dead migrations, one success, and the rollout fallout

### 2.1 The THREE dead DB-migration attempts before PR #56

TinyDB→relational-DB was attempted four times. Before restarting ANY storage work, read the dead branches (section 10 checklist).

| Attempt | Branch | Last commit | Fate |
|---|---|---|---|
| 1. SQLite route | `origin/feature/sqlite` | 2025-01-13 | Abandoned mid-way (per-store migration commits: peers, tours, terminals, app-usage, backup-stats). No in-repo rationale for abandonment. |
| 2. Copilot Postgres | `origin/copilot/migrate-database-to-postgres` | 2026-02-01 | PR [#29](https://github.com/FreeshardBase/freeshard/pull/29) closed unmerged. |
| 3. Agent Postgres | `origin/issue/25-replace-tinydb-with-postgres` | 2026-02-24 (tip lineage includes `ab73e25` "WIP claude interrupted") | PR [#34](https://github.com/FreeshardBase/freeshard/pull/34) closed unmerged. |
| 4. **Success** | `origin/replace-tinydb-with-postgres` | — | PR [#56](https://github.com/FreeshardBase/freeshard/pull/56) merged 2026-04-17 (commit `2980bfb`, merge `0837749`), released 0.38.0. Driving issue [#25](https://github.com/FreeshardBase/freeshard/issues/25) (closed 2026-06-29 in bulk backlog cleanup). |

### 2.2 Postgres rollout fallout, 0.38.0–0.38.4 (2026-04-17..23)

- SYMPTOM: four patch releases within six days of the biggest storage change in project history.
- FIX SEQUENCE: 0.38.1 `c824636` (CI app-install timeout flakiness), 0.38.2 `dc45ced` (LifespanManager `shutdown_timeout` teardown flakiness), 0.38.3 `b9dfcfd` (rclone opaque dict, see 1.2), 0.38.4 `935250b` (datetime JSONB, see 1.6). Plus `358a908` "Fix CI test hang: commit migration SQL and guard pool cleanup" inside the migration branch itself.
- STATUS: all fixed. Pattern to expect: **any infra-level minor release is followed by a burst of 2–4 patch releases within days.** Plan review and rollout capacity accordingly.

### 2.3 DB pool exhaustion under forwardAuth bursts

- SYMPTOM: batches of 500s on private apps; SPA page loads (~30 parallel requests, e.g. Actual Budget) exhausted the small connection pool via Traefik forwardAuth calls to `/internal/auth`, requests waited ~30 s then failed.
- ROOT CAUSE: `/internal/auth` runs on EVERY private-app request and did 2–3 DB queries per call against a 4-connection pool.
- FIX: pool bump (max_size=20) + in-process auth-path caches; then a follow-up commit on the same PR fixing cache invalidation correctness (signal-driven, no TTLs).
- EVIDENCE: issue [#89](https://github.com/FreeshardBase/freeshard/issues/89) (was labeled high-priority), PR [#90](https://github.com/FreeshardBase/freeshard/pull/90) (merged 2026-05-22); commits `1e0e7c1` (cache added) then `868e690` (invalidation fixed).
- STATUS: fixed. If you touch identity or app state, check whether the auth caches need an invalidation signal — the first cut of the cache shipped without one and had to be patched.

---

## 3. Docker lifecycle: stale state fixed three times

Docker objects (containers, networks) survive shard_core updates and go stale. This bit three separate times before the lesson stuck:

| # | Fix | Commit / PR | Date |
|---|---|---|---|
| 1 | Recover from stale Docker **network references** on app start | `d66d889`, PR [#54](https://github.com/FreeshardBase/freeshard/pull/54) | 2026-04-08 (0.37.4) |
| 2 | Handle stale **container name conflicts** on `docker_start_app` (symptom fix) | `fefd2f4`, PR [#63](https://github.com/FreeshardBase/freeshard/pull/63) | 2026-04-14 |
| 3 | Fix **root cause** of stale containers on core update | `751678d` (same PR window as #63) | 2026-04-14 |

- STATUS: fixed, but structural. **Rule: any new docker-start code path must recover from name conflicts and dangling network references** — do not assume clean Docker state after a core update.

Related settled work: zombie healthcheck `curl` processes fixed by tini as PID 1 (PR [#55](https://github.com/FreeshardBase/freeshard/pull/55), commit `57ac53d`); standalone `docker-compose` v1 → `docker compose` v2 plugin (issue [#35](https://github.com/FreeshardBase/freeshard/issues/35), PR [#87](https://github.com/FreeshardBase/freeshard/pull/87)); app compose templates re-rendered on startup (PR [#49](https://github.com/FreeshardBase/freeshard/pull/49)).

### 3.1 python-on-whales migration — stalled, not dead, not approved

- Oldest open issue: [#24](https://github.com/FreeshardBase/freeshard/issues/24) "Integrate Python on Whales or some other docker python lib" (2025-12-19). PR [#88](https://github.com/FreeshardBase/freeshard/pull/88) has been open with **zero reviews since 2026-05-18**.
- STATUS: open/stalled. Do not start a competing docker-lib migration, and do not treat PR #88 as accepted direction — it has never been reviewed.

---

## 4. Traefik / ingress / proxying

### 4.1 fd-exhaustion outage arc (June 2026) — the worst recent incident

- SYMPTOM: shards "up but not serving" — containers healthy, nothing reachable. Traefik logged `accept4: too many open files` (EMFILE) in a hot loop; the error spam itself filled the root disk (controller issue [#306](https://github.com/FreeshardBase/freeshard-controller/issues/306): unbounded container logs bricked shard upgrades).
- ROOT CAUSE — **two factors, both required**:
  1. Production Traefik was pinned v2.6, built with a pre-1.19 Go (measured go1.17.10; the "Go 1.16" figure in controller PR #322's prose is imprecise — see freeshard-proof-and-analysis-toolkit Recipe 1). Go only self-raises `RLIMIT_NOFILE` from 1.19 on, so Traefik ran with the soft limit.
  2. Newly provisioned shards moved to an Ubuntu 26.04 base image (controller PR [#299](https://github.com/FreeshardBase/freeshard-controller/pull/299), forced by OVH image rotation — see 6.3) where the effective per-container nofile soft limit was 1024. Older shards had the identical socket leak (`readTimeout=0` on an internet-scanned IP) but survived only because their fd ceiling was higher — "old shards are fine, must be luck" was investigated and disproven; it was ceiling height, not luck.
- FIXES (multi-repo):
  - shard_core: finite `readTimeout` on Traefik entrypoints stops the leak — commit `fd1d05b`, PR [#108](https://github.com/FreeshardBase/freeshard/pull/108) (merged 2026-06-21, released 0.39.4 on 2026-06-24).
  - controller: core v16 log rotation ([#309](https://github.com/FreeshardBase/freeshard-controller/pull/309)) — which silently did nothing at first, see 6.1; core v17 nofile ulimit ([#311](https://github.com/FreeshardBase/freeshard-controller/pull/311)) and daemon restart so config actually applies ([#312](https://github.com/FreeshardBase/freeshard-controller/pull/312)).
- DECISION — **stay on Traefik v2**: bump to v2.11 (built with Go 1.25, self-raises nofile ≈1024→64000) instead of the "obvious" risky v3 migration. Canonical statement is the closing comment on PR [#112](https://github.com/FreeshardBase/freeshard/pull/112) (closed unmerged 2026-06-24): v3 migration folded into a needs-Intent P3 backlog ticket. Confirmed in production: core v18 compose pins `traefik:v2.11`.
  - **Do not resurrect v3-prep changes** (HostRegexp→Host() style); local branch `fix/traefik-dashboard-host-rule` (2026-06-23) is that dropped work.
  - TRAP: this repo's own `docker-compose.yml` says `image: traefik:v3.6` (bumped `e78862d`, 2025-12-16) — that is the **dev/self-hosted compose only**. Production shards run the controller core-version pin (v2.11 as of core v18, 2026-07-03). Do not "fix" either to match the other without reading PR #112 first.
- PROCESS FALLOUT: the readTimeout fix was merged but sat in no released tag while shards kept failing — issue [#111](https://github.com/FreeshardBase/freeshard/issues/111). **Merged-is-not-shipped**; see freeshard-change-control. A redundant version-bump PR [#113](https://github.com/FreeshardBase/freeshard/pull/113) was closed unmerged because main had already been bumped directly — always `git fetch` and check origin/main + published releases before opening a release PR.
- STATUS: fixed (0.39.4 + core v17/v18); Traefik-v3 migration = open backlog, decided-not-now.

### 4.2 Content-Type proxy landmine

- SYMPTOM: every proxied **write** to the controller returned 422; reads worked fine. Red herring chased: body double-encoding.
- ROOT CAUSE: `call_backend` relayed bodies but dropped the `Content-Type` header (Python `requests` sets none for `data=<bytes>`). Harmless for years, until the controller's FastAPI upgrade made JSON parsing strict about the header — a latent bug armed by a *dependency bump in a different repo*.
- EVIDENCE: issue [#93](https://github.com/FreeshardBase/freeshard/issues/93) (high-priority), PR [#94](https://github.com/FreeshardBase/freeshard/pull/94) (merged 2026-05-27). Diagnosed with tcpdump in the container netns because Traefik swallowed the detail.
- STATUS: fixed.

### 4.3 call_backend/call_peer is a repeat offender — full rap sheet

| Bug | Evidence | Fixed |
|---|---|---|
| Query strings not forwarded to controller | PR [#19](https://github.com/FreeshardBase/freeshard/pull/19) | 2025-12-13 |
| Slow proxying (buffered instead of streamed bodies) | issue [#38](https://github.com/FreeshardBase/freeshard/issues/38), PR [#39](https://github.com/FreeshardBase/freeshard/pull/39) | 2026-03-22 |
| Content-Type dropped on writes | [#93](https://github.com/FreeshardBase/freeshard/issues/93)/[#94](https://github.com/FreeshardBase/freeshard/pull/94) | 2026-05-27 |

Checklist when touching any sign-and-forward proxy code here: forward query strings, forward Content-Type (and other load-bearing headers), stream bodies. Note `_get_app_for_ip_address` in `shard_core/web/internal/call_peer.py` is `lru_cache`'d and carries a "todo: test this" — untested hot path.

### 4.4 Splash-screen stalemate (#91/#92) — UNRESOLVED, do not code around it

- GOAL: embed the real upstream error response (hidden) in the splash page so it's visible in dev tools — issue [#91](https://github.com/FreeshardBase/freeshard/issues/91).
- CONFLICT: PR [#92](https://github.com/FreeshardBase/freeshard/pull/92) implements an internal reverse proxy; maintainer max-tet requested changes ("too complex — no need for a separate endpoint"). The agent's counter-argument: Traefik's errors middleware discards the upstream body, so some proxy is technically required. No movement since 2026-05-27.
- STATUS as of 2026-07-03: **open architectural disagreement.** Do not merge-adjacent work that presumes either outcome; if you pick this up, resolve the disagreement in the issue thread first (see freeshard-change-control for how decisions get made).

---

## 5. CI and release-process incidents

### 5.1 GitLab→GitHub CI bring-up chain, 0.31.0→0.32.0 (six tags in three days, 2025-02-24..26)

- CONTEXT: GitLab registry credentials had already died once (0.30.4–0.30.6, commits `584113e`, `4d6e30f`, 2025-01-20..21). Full migration: `b33eada` "delete .gitlab-ci.yml" + `0729394` "add github actions" (2025-02-24).
- SYMPTOM: pipeline debugged by trial and error directly on main: `b258fbd` "fix pipeline env vars", `d67abc6` "fix pipeline permissions", `d2acc45` "try another way to handle slug vars", `59c4e07` "use sha as label temporarily", `42cf5c6` "hard code registry path", `d309113` "skip json-schema and api-docs for now".
- STATUS: pipeline works, BUT the "temporary" skip from `d309113` (2025-02-26) is **still in place** — the json-schema job is commented out in `.github/workflows/release.yml` (line ~75) as of 2026-07-03. If your change relies on published JSON schemas or API docs, they are not being published.

### 5.2 Chronic CI flakiness (multi-year)

`tests/conftest.py` is the most fix-touched file in the repo (33 fix-commit touches). Landmarks: `dcf6207` skip flaky peer-call tests (2022), `28964fd` network not torn down between tests, `aad605a` telemetry test converted to unit test, `c824636` install-timeout bump (2026), `dc45ced` LifespanManager shutdown_timeout. Before "fixing" a flaky test, check freeshard-testing-and-qa — most flake classes here have a known cause.

### 5.3 Reverts are rare — treat them as signals

Only ONE true `git revert` exists in ~784 commits: `3ee5a71` (reverts `e0c4bed`, 2023 test-infra). The project's failure mode is not revert-thrash; it is *fix-tails* (patch bursts after infra releases) and *abandoned branches*. When you see an unmerged branch, assume "pending decision or dead end", never "free code to merge" — check the PR/issue state first.

---

## 6. Controller-side incidents shard work must know about

These live in FreeshardBase/freeshard-controller but bite shard_core work directly.

### 6.1 Docker daemon.json reload-vs-restart trap

- SYMPTOM: core v16 shipped daemon-wide log rotation (`max-size`/`max-file`); it silently did nothing.
- ROOT CAUSE: it was applied with `systemctl reload docker`. SIGHUP reloads only a whitelisted subset of daemon.json — **log-driver/log-opts and default-ulimits are NOT in it**, and containers keep stale in-memory values even when recreated after a reload.
- EVIDENCE: controller PRs [#309](https://github.com/FreeshardBase/freeshard-controller/pull/309) (v16, ineffective) → [#312](https://github.com/FreeshardBase/freeshard-controller/pull/312) "v17 daemon-wide docker config + restart (rotation actually applies, fd ceiling)".
- STATUS: fixed in core v17. Rule: log-opts/ulimit changes need `systemctl restart docker` (bounces all containers — maintenance window), never `reload`.

### 6.2 Migration-delivery trap — the sentinel guards the wrong thing

- SYMPTOM: host migrations silently never ran on fresh shards and on version-skipping upgrades (e.g. v15→v17); a broken shard was found where the nofile migration had never executed.
- ROOT CAUSE: script delivery was version-scoped (only the target version's scripts were uploaded), and the `.migrations_applied` sentinel only prevented *re-running* — it gave zero protection against *never-delivered* scripts.
- EVIDENCE: controller issue [#307](https://github.com/FreeshardBase/freeshard-controller/issues/307), fix PR [#308](https://github.com/FreeshardBase/freeshard-controller/pull/308) (cumulative union of all versions' scripts, globally-unique `vN-NN-description.sh` names, numeric ordering); follow-up [#323](https://github.com/FreeshardBase/freeshard-controller/pull/323) replaced run-once sentinels with idempotent reconcilers run on every converge.
- STATUS: fixed. Design rule: prefer idempotent reconcile-on-every-converge over run-once sentinels.

### 6.3 OVH base-image rotation broke provisioning

- SYMPTOM: shard provisioning failed with a cryptic `list index out of range`; auto-provisioning disabled itself.
- ROOT CAUSE: OVH removed the non-LTS "Ubuntu 25.04" image from the region without notice; code did exact-name match + `[0]` on an empty list.
- EVIDENCE: controller PRs [#299](https://github.com/FreeshardBase/freeshard-controller/pull/299) (bump image), [#300](https://github.com/FreeshardBase/freeshard-controller/pull/300) (image name becomes a controller-managed runtime setting), [#301](https://github.com/FreeshardBase/freeshard-controller/pull/301) (clear error when image/key not found).
- STATUS: fixed; lessons: pin LTS images only; provider provisioning inputs are runtime settings, not static config. Side effect: the Ubuntu 26.04 image was factor 2 of the fd-exhaustion outage (4.1).

### 6.4 OVH SDK singleton auth-brick

- SYMPTOM: after one transient OVH token-endpoint 500, ALL subsequent OVH calls returned "401 You must login first" until controller restart; two shard deletions failed and the VMs kept billing.
- ROOT CAUSE: process-level `ovh.Client` singleton cached a stale token with no recovery path.
- EVIDENCE: controller issue [#275](https://github.com/FreeshardBase/freeshard-controller/issues/275) (closed 2026-06-05).
- STATUS: fixed. Pattern: SDK singletons with token caching need auth-error reset+retry.

### 6.5 Lexical version sort — "everything was fine until v10"

- SYMPTOM: the system thought core v9 was newer than v10; bit in four places at once (backend latest-version, `/core-versions` list, frontend latest, upgrade dropdown).
- ROOT CAUSE: version directory names sorted as strings: `"v10" < "v9"`.
- EVIDENCE: controller PRs [#260](https://github.com/FreeshardBase/freeshard-controller/pull/260), [#262](https://github.com/FreeshardBase/freeshard-controller/pull/262) (merged 2026-05-26).
- STATUS: fixed. Rule: never sort version identifiers lexically; use a numeric ordinal, and the frontend trusts backend order. Related: shard_core's move to real semver is open — issue [#118](https://github.com/FreeshardBase/freeshard/issues/118).

### 6.6 Pricing rounding divergence — Python `round()` vs JS `Math.round()`

- SYMPTOM: displayed price label could disagree with the actual PayPal charge by 1 cent on half-cent results.
- ROOT CAUSE: Python `round()` is banker's rounding, JS `Math.round()` is half-up; they agreed under the old formula and diverged once the 19%-VAT factor produced half-cent values.
- EVIDENCE: controller PR [#298](https://github.com/FreeshardBase/freeshard-controller/pull/298) — switched backend to half-up `int(x + 0.5)`, bit-identical to `Math.round` for positive values; sibling PRs web-terminal#30 and landing-page#15 (formula is manually duplicated across repos and must change in lockstep).
- STATUS: fixed. Rule: never use Python `round()` in pricing code.

### 6.7 PayPal quantity-pricing workaround

- CONSTRAINT: PayPal forbids repricing a running subscription (`422 OVERRIDES_ON_SAME_PLAN_NOT_ALLOWED`).
- ACCEPTED DESIGN: ONE plan priced €0.01 with `quantity_supported`; quantity = price in cents; resize = quantity revision, applies next cycle. Webhooks must read `resource.quantity`, not `last_payment` (lags a cycle).
- REJECTED ALTERNATIVES: per-resize plan overrides (hard 422 above); ping-ponging between two €1 plans (rejected in review as unmaintainable); redirect-based resize (broke behind the shard proxy — reworked to fully in-window PayPal JS SDK, controller PR [#292](https://github.com/FreeshardBase/freeshard-controller/pull/292)).
- EVIDENCE: controller PRs [#291](https://github.com/FreeshardBase/freeshard-controller/pull/291) (quantity pricing), [#316](https://github.com/FreeshardBase/freeshard-controller/pull/316) (runbook corrected to penny-quantity model).
- STATUS: live in production since 2026-06-23. Do not propose plan-per-price designs.

---

## 7. Identity direction: Authelia is dead, embedded OIDC is the path

- HISTORY: PR [#86](https://github.com/FreeshardBase/freeshard/pull/86) "Add Authelia as core IAM service" is still open but **orphaned** — never reviewed, and its driving issue [#36](https://github.com/FreeshardBase/freeshard/issues/36) was closed 2026-06-29 in a bulk backlog cleanup (same-minute closures of #18, #33, #36, #37, #71, #72; #25 shortly after). Branch: `origin/clayde/issue-36-authelia-yaml-backend` (2026-05-18).
- DECISION (2026-06-12, recorded outside this repo): identity = embedded OIDC provider inside shard_core (Authlib), NOT Authelia. A PoC exists on the local-only branch `spike/oidc-provider-poc` (last commit 2026-06-12, zero-click Immich login); production implementation had not started in this repo as of 2026-07-03.
- STATUS: Authelia = decided-won't-do. **Do not resurrect PR #86 or issue #36.** All OIDC work goes through freeshard-oidc-identity-campaign, which owns the decision gates.

---

## 8. Platform traps without a clean "fixed" commit

### 8.1 Idle-sleep × PWA service worker

Idle-slept apps cold-start on demand, but a split web/backend app (seen with KitchenOwl) serves a static 200 before its backend is ready — shard_core thinks "reachable" and skips the splash. Worse, a PWA service worker serves the cached shell without ever hitting the shard, then hard-redirects to `/unreachable`; after version bumps the stale cached frontend trips `min_frontend_version` until a hard refresh. Partial mitigation: gate the web container with `depends_on: condition: service_healthy` in the app's compose (app-repository side). General rule: scale-to-zero in front of SPAs/PWAs lies to your proxy. (No public tracking issue found as of 2026-07-03; treat details as unverified-but-load-bearing.)

### 8.2 Ops-visibility gaps from the July 2026 Immich incidents — OPEN

Two real incidents (DB-extension migration killed mid-flight; OOM restart loop shown to the user as a bare 502) produced two open issues: [#121](https://github.com/FreeshardBase/freeshard/issues/121) no-interruption window for app updates so on-startup migrations finish, and [#120](https://github.com/FreeshardBase/freeshard/issues/120) make OOM kills / restart loops visible. STATUS: open as of 2026-07-03 — check current state before starting related work.

### 8.3 The overbuilt agentic dev-loop — retired after one day

The first autonomous dev-loop build (in-container execution, derived-phase state machine, review-packet pipeline) was retired the day after going live as overbuilt, replaced by the current dumb grind script (one fresh headless session per issue; GitHub is the only state store; nothing auto-merges). EVIDENCE: [ClaydeCode/me PR #100](https://github.com/ClaydeCode/me/pull/100) "Gate freeshard loop behind CLAYDE_FS_ENABLED (default off)" (merged 2026-06-30). LESSON: for agent tooling here, the dispatcher stays dumb and all intelligence lives in the per-issue agent — don't rebuild the state machine.

---

## 9. Repo-archaeology command set

These are the exact commands used to build this chronicle. **Path trap:** the codebase was renamed `portal_core/` → `shard_core/` in commit `88e5842` (2025-02-11, part of open-sourcing). Any history search MUST cover both prefixes.

```bash
# Tag → date table (release cadence, incident-burst detection)
for t in $(git tag | sort -V); do echo "$t $(git log -1 --format=%ad --date=short $t)"; done

# Churn: most-changed files ever
git log --format= --name-only | sort | uniq -c | sort -rn | head -30

# Fix hotspots: files most touched by fix-commits
git log -i --grep=fix --format= --name-only | sort | uniq -c | sort -rn | head -30

# History of one file ACROSS the rename (list both paths; --follow only takes one path)
git log --oneline -- shard_core/service/backup.py portal_core/service/backup.py

# Stale-branch triage: what each remote branch has that main doesn't
for b in $(git branch -r | grep -v HEAD); do echo "== $b"; git log --oneline main..$b | head -5; done

# Resolve tag/branch topology surprises (e.g. the 0.37.5 backport)
git branch -a --contains <tag>

# Which release first contained a commit
git tag --contains <sha> | sort -V | head -1
```

gh gotchas for this org: `gh issue view N --comments` fails ("Projects classic deprecated") — use `--json body,comments`. Issue and PR numbers share one sequence; check `gh api repos/FreeshardBase/freeshard/issues/N -q '.pull_request!=null'` when unsure which one a "Fix #N" commit means (e.g. #54, #63 are PRs, not issues).

---

## 10. Checklist: before restarting storage / DB / docker-lib work

Copy this into your plan and tick each item:

- [ ] Read the three dead DB-migration branches before proposing any storage change: `git log --oneline main..origin/feature/sqlite`, `...main..origin/copilot/migrate-database-to-postgres`, `...main..origin/issue/25-replace-tinydb-with-postgres`. The merged pattern is `origin/replace-tinydb-with-postgres` → PR #56.
- [ ] For docker-lib work: read PR [#88](https://github.com/FreeshardBase/freeshard/pull/88) (python-on-whales, open, unreviewed) and issue [#24](https://github.com/FreeshardBase/freeshard/issues/24) — don't fork a fourth approach.
- [ ] Any new docker-start path handles stale container names AND stale network refs (section 3).
- [ ] Backup changes keep: opaque-dict rclone parsing (1.2), CronTask exception safety (1.4), marker-blob write (1.5), datetime serialization (1.6), rclone-flag-vs-pinned-binary check (1.7).
- [ ] Proxy changes forward query strings, Content-Type, and stream bodies (4.3).
- [ ] No Traefik v3 work — settled in PR [#112](https://github.com/FreeshardBase/freeshard/pull/112); v2.11 is the production pin (4.1).
- [ ] No Authelia work — settled; embedded OIDC is the path (7).
- [ ] Re-check the live state of anything marked OPEN here (`gh issue view N --repo FreeshardBase/freeshard --json state,title`) — this file is a snapshot dated 2026-07-03.

## When NOT to use this skill

- You have a **live symptom to triage right now** → freeshard-debugging-playbook (it has the symptom→experiment tables; this file is the historical record behind them).
- You need **why the architecture is the way it is** / current invariants → freeshard-architecture-contract.
- You need **how to classify, gate, or release a change** (including merged-is-not-shipped mechanics) → freeshard-change-control.
- You need **crypto/signatures/Traefik-forwardAuth theory** → freeshard-domain-reference.
- You are working the **OIDC identity provider** → freeshard-oidc-identity-campaign (it owns the live decision gates; section 7 here is only the back-story).
- You want **analysis technique** (how investigations like 4.1 were actually run) → freeshard-proof-and-analysis-toolkit.

## Provenance and maintenance

Written 2026-07-03 by repo archaeology (git log/tags/branches at local checkout, origin state via gh) plus GitHub issue/PR reads on FreeshardBase/freeshard, FreeshardBase/freeshard-controller, and ClaydeCode/me. All commit hashes, tag dates, issue/PR states, and titles were individually verified on 2026-07-03. Maintainer knowledge without a public artifact is labeled inline (sections 4.1 partial, 7, 8.1).

Drift-prone facts and how to re-verify each:

| Fact (as of 2026-07-03) | Re-verify with |
|---|---|
| PR #92 splash stalemate still open/CHANGES_REQUESTED | `gh pr view 92 --repo FreeshardBase/freeshard --json state,reviews` |
| PR #88 python-on-whales still open, zero reviews | `gh pr view 88 --repo FreeshardBase/freeshard --json state,reviews` |
| PR #86 Authelia still open (orphaned) | `gh pr view 86 --repo FreeshardBase/freeshard --json state` |
| Issues #120, #121 still open | `gh issue view 120 121 --repo FreeshardBase/freeshard --json state` (one call each) |
| Production Traefik pin is v2.11 (core v18 latest) | `gh api repos/FreeshardBase/freeshard-controller/contents/freeshard-controller-backend/data/core-versions --jq '.[].name' \| sort -V \| tail -1`, then fetch that version's docker-compose.yml and grep `traefik:` |
| Dev compose still diverges (traefik:v3.6) | `grep 'image: traefik' docker-compose.yml` |
| json-schema/api-docs release jobs still skipped | `grep -n '#  json-schema' .github/workflows/release.yml` |
| spike/oidc-provider-poc still local-only / no production OIDC branch | `git branch -r \| grep -i oidc` |
| Dead migration branches still exist on origin | `git branch -r \| grep -Ei 'sqlite\|postgres'` |
| Latest release tag (was 0.39.4) | `git fetch --tags && git tag \| sort -V \| tail -1` |
| Semver migration #118 still open | `gh issue view 118 --repo FreeshardBase/freeshard --json state` |
