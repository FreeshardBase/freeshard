---
name: freeshard-ecosystem-contracts
description: Cross-repo contracts between shard_core (this repo) and freeshard-controller, web-terminal, app-repository, landing-page — and how they drift. Use when a change spans repos or touches a contract surface. TRIGGER on: shard_core/data_model/backend/*, `just get-types`, shard_core/data_model/profile.py, service/signed_call.py, service/portal_controller.py, service/freeshard_controller.py, web/protected/management.py, web/internal/call_backend.py, data_model/app_meta.py version bumps, docker-compose.yml image pins, pricing changes, "field added on the controller doesn't show up in the web-terminal", "type sync", "app store zip", "shared secret", "HTTP message signatures". SKIP when: the change is confined to shard_core internals with no controller/web-terminal/app-repo surface (use freeshard-architecture-contract), you need crypto/forwardAuth theory (use freeshard-domain-reference), you're releasing/deploying (use freeshard-run-and-operate and freeshard-change-control), or you're debugging a live failure (use freeshard-debugging-playbook).
---

# Freeshard ecosystem contracts

This repo (`freeshard`, code name `shard_core`) is one node in a multi-repo system. Most contracts between the repos are **convention-only**: a hand-maintained file copy, hardcoded URLs, and a duplicated pricing formula. They drift silently. This skill maps every contract, gives the sync procedures, and records the incidents that prove what happens when you skip a step.

Terms used throughout (defined once):

| Term | Meaning |
|---|---|
| **shard** | One customer VM running the shard_core stack (Traefik + postgres + shard_core + web-terminal via Docker Compose) |
| **controller** | freeshard-controller: central cloud service at controller.freeshard.net; provisions VMs (OVH), billing (PayPal), rolls out core versions to shards |
| **core version** | A numbered fleet rollout unit (`v18`, `v19`, ...) — a directory in the controller repo containing the docker-compose.yml + scripts the controller pushes to every shard |
| **web-terminal** | Vue 2 SPA served on each shard; the end-user UI |
| **app store** | Azure blob storage container `app-store` holding app zips + `store_metadata.json`, built from the app-repository repo |
| **backend copy** | `shard_core/data_model/backend/` — a verbatim copy of the controller's pydantic models, synced by `just get-types` |

## 1. Repo map

All siblings are checked out under `/home/ubuntu/projects/freeshard/` (each its own git repo; org = FreeshardBase on GitHub).

| Repo | Role | Stack | Ships as |
|---|---|---|---|
| `freeshard` (this) | Per-shard backend: app orchestration, Traefik config, pairing, backup | FastAPI + PostgreSQL + docker-py | `ghcr.io/freeshardbase/freeshard:<tag>` on GitHub Release (`.github/workflows/release.yml`) |
| `freeshard-controller` | Central: VM provisioning, billing, core-version rollout, email relay, diagnostics | FastAPI backend + Vue 3/Quasar frontend | Azure-hosted service |
| `web-terminal` | Shard UI | Vue 2.6 + Vuex 3 + Bootstrap-Vue, plain JS, **no generated API client** | `ghcr.io/freeshardbase/web-terminal:<tag>`, pinned separately in shard compose files |
| `app-repository` | App catalog: `apps/<name>/{app_meta.json, docker-compose.yml.template, icon, update_check.py}` | Python build script + GH Actions | Uploaded to Azure blob `app-store/master/all_apps` (`.github/workflows/deploy.yml:28`) |
| `documentation` | docs.freeshard.net | MkDocs Material | Static site (its README.md is stale legacy "Portal" content — trust its agents.md) |
| `landing-page` | Marketing site incl. pricing widget | Astro | Static site |
| `cicd-image` | CI container used by this repo's workflows | Docker | `ghcr.io/freeshardbase/cicd-image:1.0.3` (release.yml:30) |

Naming residue: the project was formerly "Portal". `portal_controller.py`, the `portal` docker network, `X-Ptl-*` headers, `{{ portal.domain }}` template vars, and `minimum_portal_size` all predate the rename — they are live code, not dead code.

## 2. Contract map

| # | Producer → Consumer | Transport | Auth | Typed? |
|---|---|---|---|---|
| C1 | shard → controller | HTTPS to `settings().freeshard_controller.base_url` (prod: `https://controller.freeshard.net`, config.toml:64) | HTTP Message Signatures, `RSA_PSS_SHA512`, `keyid` = identity short_id (`shard_core/service/signed_call.py:26-30`); controller verifies with same algorithm (`freeshard_controller/api/auth.py`) | Responses parsed with the **backend copy** models |
| C2 | controller → shard | `https://{shard.domain}/core/management/{path}` | Header `authorization: <shared_secret>`; shard validates by re-fetching `api/shards/self` and comparing (`shard_core/service/freeshard_controller.py:28-44`) | Shard-side routers: `shard_core/web/management/{apps,notify,pairing_code}.py` |
| C3 | web-terminal → controller | Via shard's **untyped pass-through** `/core/protected/management/{rest:path}` (`shard_core/web/protected/management.py:31-37`) — shard signs and relays bytes | Terminal JWT cookie (Traefik forwardAuth) on the shard hop; C1 signature on the controller hop | **No.** Only `/core/protected/management/profile` is typed (`response_model=profile.Profile`, management.py:16) |
| C4 | app-repository → shard + web-terminal | Azure blob `https://storageaccountportab0da.blob.core.windows.net/app-store/...` | None (public blob) | `store_metadata.json` + zips; format = AppMeta (section 7) |
| C5 | controller backend → controller frontend | OpenAPI spec → generated TS client | n/a | Yes — the only generated contract in the system (section 6) |

WARNING (stale doc): `agents.md` in this repo claims Ed25519 crypto. The code is **RSA-4096 with PSS padding**; signatures are `RSA_PSS_SHA512` (`shard_core/service/crypto.py`, `signed_call.py:27`). Never implement against Ed25519.

### C1 endpoints shard_core actually calls

| Endpoint | Caller | Note |
|---|---|---|
| `GET api/shards/self` | `service/portal_controller.py:22` (profile refresh) and `service/freeshard_controller.py:21` (shared-secret refresh) | Two client modules for the same controller: `portal_controller._call_freeshard_controller` **prepends `api/`** (portal_controller.py:16); `freeshard_controller.call_freeshard_controller` does **not** — its callers pass `api/...` themselves |
| `GET api/shard_backup/backup_sas_url` | `service/portal_controller.py:40` | Returns SAS URL for rclone backup |
| `POST api/telemetry` | `service/telemetry.py:39` | |
| `POST {settings().management.api_url}/app_usage` | `service/app_usage_reporting.py:54-55` | config.toml:58 default is a **legacy Azure Functions URL** (`ptlfunctionapp.azurewebsites.net/api/management`), not controller.freeshard.net; the fleet v18 compose sets no override env var. The controller has its own `api/app_usage` router. Where production reports actually land is unverified as of 2026-07-03 — check before touching |

Related dead config: `[portal_controller]` in config.toml (settings.py:124) is defined but no code reads `settings().portal_controller` — see freeshard-config-and-flags.

## 3. The type-sync copy: `just get-types`

`shard_core/data_model/backend/` is a **verbatim file copy** of `../freeshard-controller/freeshard-controller-backend/freeshard_controller/data_model/` (justfile:13-24). The recipe `rm -rf`'s the target, `cp -r`'s from the **LOCAL sibling checkout**, and prepends `# DO NOT MODIFY - copied from freeshard-controller` to every file. It is not OpenAPI-generated. There is **no CI enforcement** (only release.yml, snapshot.yml, test.yml exist in `.github/workflows/`).

**Invariant — pull the source first.** The sync source is whatever your local controller checkout happens to be on:

```bash
cd ../freeshard-controller && git checkout main && git pull
cd ../freeshard && just get-types
```

As of 2026-07-03 the local controller checkout was stale (local main `1e28abe` vs origin `b495a676`), and the copy shows **bidirectional drift** in `subscription_model.py`: the copy has `approval_url` which controller main removed, and lacks `plan_id` which controller main added — proof that a past sync ran against a checkout that had diverged from what later landed on main.

Blast radius of a sync: the copy contains ~10 files but shard_core runtime imports only 2 of them directly —
`shard_model` (from service/freeshard_controller.py:3, service/portal_controller.py:4, data_model/profile.py:6), `telemetry_model` (from service/telemetry.py:4) — plus tests (tests/conftest.py, tests/test_profile.py, tests/test_terminals.py, tests/test_telemetry.py). But `shard_model` itself transitively pulls in `permission_model` (`PermissionHolder`), `subscription_model` (`SubscriptionStatus`), and `telemetry_model` (backend/shard_model.py:9-11), so drift in those files is runtime-relevant too: `ShardResponse` inherits `permissions: Set[Permission]` and carries `subscription.status: SubscriptionStatus`, so a controller payload with an enum member the stale copy lacks fails `ShardResponse` validation in `refresh_profile()`. The copy also drags in modules shard_core never uses (`email_model` imports jinja2 and renders controller-only templates; `promo_code_model`, `revenue_share_model`, `api_token_model` are unused) — a new controller-only import can break shard_core after a sync, so run the test suite after every `get-types`.

### The incident that defines this contract (why staleness is silent)

Data can flow through the untyped C3 proxy perfectly and **still be dropped** by shard_core's own typed profile path, because that path re-serializes twice:

1. `refresh_profile()` parses the controller's `api/shards/self` JSON with the **copied** `ShardResponse` — pydantic silently discards fields the stale copy doesn't declare.
2. `Profile.from_shard()` maps a hand-picked subset into shard_core's own `Profile` model (`data_model/profile.py:29-47`).

Both layers must know a field or the web-terminal never sees it. This shipped as a real bug: `billing_enabled`/`paypal_client_id`/`paypal_environment` and `ShardSubscriptionSummary.last_payment_failed_at`/`ended` were stripped, so the subscription UI stayed hidden for subscribed shards. Fixed by commits `6d4b101` (re-sync) and `e55ce51`, merged as https://github.com/FreeshardBase/freeshard/pull/102 (2026-06-05). The fix also introduced the defensive pattern that `Profile.from_shard` now uses for every newer field so a lagging copy degrades to defaults instead of crashing:

```python
billing_enabled=getattr(shard, "billing_enabled", False),   # profile.py:44
```

Keep that pattern for any field you add.

### Drift check (no clone update needed)

Preferred — the maintained script (exit 0 = in sync, 1 = drift):

```bash
.claude/skills/freeshard-diagnostics-and-tooling/scripts/check-type-drift.sh
```

Quick manual check of one file:

```bash
f=shard_model.py
gh api "repos/FreeshardBase/freeshard-controller/contents/freeshard-controller-backend/freeshard_controller/data_model/$f?ref=main" \
  --jq '.content' | base64 -d | diff <(tail -n +3 shard_core/data_model/backend/$f) -
```

(`tail -n +3` strips the injected DO-NOT-MODIFY header.)

Drift state as of 2026-07-03 (all verified with the diff above):

| File | Drift | Matters to shard_core? |
|---|---|---|
| `shard_model.py` | in sync | the one that matters most |
| `subscription_model.py` | copy has `approval_url`, remote has `plan_id` (bidirectional) | yes, transitively: shard_model imports `SubscriptionStatus` from it (backend/shard_model.py:10), so the file loads at runtime. The copy's `approval_url` is pure legacy — web-terminal main dropped it for the PayPal SDK flow reading `plan_id` (section 5) |
| `settings_model.py` | copy lacks `NEW_INSTANCE_IMAGE` | not imported by shard_core |
| `permission_model.py` | copy lacks `OPEN_DIAGNOSTIC`, `RUN_DIAGNOSTIC` | yes, transitively: shard_model imports `PermissionHolder` from it (backend/shard_model.py:9), and `ShardResponse` inherits its `permissions` set — a controller shard payload carrying one of the missing enum members fails `ShardResponse` validation |
| `diagnostic_model.py` | missing from copy entirely | not imported by shard_core |

## 4. Checklist: controller field → web-terminal UI

Use this whenever a value produced by the controller must appear in the shard UI. Skipping steps 2–4 silently drops the field (the PR #102 failure mode).

1. Add the field on the controller (`ShardBase`/`ShardResponse`/`ShardSubscriptionSummary` in `freeshard_controller/data_model/shard_model.py`) → merged to controller main.
2. `cd ../freeshard-controller && git checkout main && git pull` — sync source must be fresh.
3. `cd ../freeshard && just get-types` → verify the diff touches only expected files; run `pytest`.
4. Add the field to `Profile` **and** to `Profile.from_shard` in `shard_core/data_model/profile.py`, using `getattr(shard, "field", default)` so an older copy degrades instead of crashing. Add a mapping test in `tests/test_profile.py`.
5. web-terminal reads it from `GET /core/protected/management/profile` (store.js:109; force-refresh variant `?refresh=true` at store.js:116). No client generation — just read `profile.data.<field>` in the component.
6. Ship: both a shard_core release **and** a web-terminal release may be needed, and neither reaches customers until a new controller core version pins them (section 8; gates in freeshard-change-control).

## 5. web-terminal ↔ controller: the untyped pass-through

`/core/protected/management/{rest:path}` (management.py:31-37) forwards any method + body from the paired terminal to the controller, signed as the shard. web-terminal uses it for billing:

- `POST /core/protected/management/api/shards/self/resize` (origin/main Settings.vue:551 immediate path, :595 SDK path; JSON body `{new_vm_size}`)
- `POST /core/protected/management/api/shards/self/subscribe` (origin/main Settings.vue:642)

There is **no schema contract anywhere on this chain** — shard_core relays bytes. Two known weak points:

1. **Content-Type is not forwarded.** Issue https://github.com/FreeshardBase/freeshard/issues/93 (controller 422'd every proxied write after its FastAPI bump) was fixed in https://github.com/FreeshardBase/freeshard/pull/94 — but only for the *other* proxy, `/internal/call_backend` (`shard_core/web/internal/call_backend.py:34-40`, which now forwards Content-Type, query params, and streams). The management pass-through still forwards neither Content-Type nor query strings (verified 2026-07-03). Why current billing writes survive this is unverified — before routing any **new** write through it, either test against the real controller or port the call_backend header/query/streaming fixes over.
2. **Response-shape drift is only caught by grep.** Controller main's `ResizeResponse` replaced `approval_url` with `plan_id` (section 3 drift table), and web-terminal main followed: the redirect flow was replaced by an in-window PayPal SDK revise flow that reads `r.plan_id` (origin/main Settings.vue:599; web-terminal PR https://github.com/FreeshardBase/web-terminal/pull/29, merged 2026-06-05). The backend-copy's `approval_url` field is pure legacy. Nothing automated would have flagged the breaking rename — the coordinated SDK rework absorbed it. When changing a controller response consumed by web-terminal, grep web-terminal for the field name **on a freshly fetched origin/main, never the possibly-stale local checkout** — that grep *is* the contract check.

## 6. Controller-side changes: OpenAPI sync order

The controller has its own, separate typed pipeline for its frontend. After changing controller backend routes/models, run the chain in this order (documented in the workspace-level `../agents.md:91`):

```bash
cd ../freeshard-controller/freeshard-controller-backend && just openapi      # regenerate spec
cd ../freeshard-controller-app && just api-client                            # regenerate TS client (never hand-edit generated-sources)
cd ../../freeshard && just get-types                                          # refresh shard_core's copy (after pulling, section 3)
```

## 7. AppMeta: the self-migrating app format

`app_meta.json` (contract C4, authored in app-repository, parsed by shard_core) is versioned by `CURRENT_VERSION = "1.2"` (`shard_core/data_model/app_meta.py:13`). A `model_validator(mode="before")` walks `app_meta_migration.migrations` from the zip's `v` up to CURRENT_VERSION (app_meta.py:132-135), so old store zips keep working.

To evolve the format: bump `CURRENT_VERSION`, add `migrate_X_to_Y` in `shard_core/data_model/app_meta_migration.py` keyed by the **old** version. Each migration must set `values["v"]` to the new version — otherwise the loop raises `"migration seems to be stuck, perhaps a migration does not increment the version number?"` (app_meta.py:135). Then update the authoring docs in `app-repository/agents.md` so new apps are written in the new format.

Shards download app zips from `{apps.app_store.base_url}/{container_name}/master/all_apps/{name}/{name}.zip` (config.toml:26-28 → `service/app_installation/worker.py:181-182`). app-repository's GH Actions uploads there (`deploy.yml:28`; branch and `preview/<head_ref>` paths too). web-terminal fetches `store_metadata.json` and icons from the **same blob URL hardcoded** in 4 files (Apps.vue:220, AppStoreEntry.vue:163, UsagePromptModal.vue:109, Banner.vue:13) — changing the storage account means touching both repos, one of them in scattered literals.

### Platform rules an app must obey (enforced by shard_core behavior, documented in `app-repository/agents.md`)

| Rule | Mechanism / evidence |
|---|---|
| `access` per path: `private` = paired devices only, `public` = anyone, `peer` = peer shards (agents.md:62) | Every app router gets Traefik forwardAuth to `/internal/auth` (`service/traefik_dynamic_config.py:171`); the auth endpoint rejects non-terminal clients for PRIVATE and non-peer for PEER paths, and lets anything through for public paths (`web/internal/auth.py:88-100`). So "public skips auth" means the check passes for anonymous — the app must do its own token/HMAC auth on public paths |
| `lifecycle.always_on: true` = never auto-stopped; mutually exclusive with `idle_time_for_shutdown` (validator at app_meta.py:103-109) | Cost = permanently held RAM; reserve for IoT/messaging apps |
| No `docker exec` first-user bootstrap | Shard owners have no shell access by design — hard-exit criterion `j` in `app-repository/.claude/skills/add-app/reference/exit-criteria.md` |
| Split web/backend apps must health-gate the entrypoint container (`depends_on: condition: service_healthy`) | Otherwise the entrypoint 200s before the backend is up and the wake-from-idle splash lies; see `app-repository/apps/kitchenowl/docker-compose.yml.template:14-16` |
| Email only via the controller relay | `POST /api/email_relay` on the controller, shard-signature auth, sends to the shard **owner only**, default 10/rolling-hour (`freeshard_controller/settings.py:101 relay_rate_limit_per_hour`). No general SMTP from shards, by design |
| FOSS-only license gate | Allowlist (MIT, Apache-2.0, BSD-*, GPL-*, AGPL-3.0, LGPL-*, MPL-2.0, ISC, Unlicense, CC0-1.0) in exit-criteria.md:38; source-available (BSL/SSPL/Elastic) is a hard block, recorded in `app-repository/blocked_apps/` |
| `minimum_portal_size` biased to smallest tier that runs (agents.md:83,313); only the entrypoint container joins the `portal` docker network (agents.md:241) | |

## 8. Version pins: who bumps what

There are **two different compose files** and they currently differ. The traefik pin divergence is an **unresolved inconsistency** (see freeshard-change-control §4.2) — don't "fix" one to match the other without an issue:

| | `freeshard/docker-compose.yml` (this repo — dev/self-hosted) | Controller `data/core-versions/v18/docker-compose.yml` (fleet — what customer shards actually run) |
|---|---|---|
| traefik | `v3.6` (pinned Dec 2025, commit e78862d) | `v2.11` — deliberate: stay on v2, v3 migration is a needs-Intent backlog item (decision recorded in closed PR https://github.com/FreeshardBase/freeshard/pull/112) |
| postgres | `17` | `17` |
| shard_core | `0.39.4` | `0.39.4` |
| web-terminal | `0.37.4` (lagging; not bumped) | `0.39.4` |

All values as of 2026-07-03, from `git show origin/main:docker-compose.yml` and the controller repo's `core-versions/v18` on main. Latest GitHub Releases at that date: freeshard `0.39.4` (2026-06-24), web-terminal `0.39.4` (2026-06-05).

Who bumps what:

| Artifact | Bumped by | Command / trigger |
|---|---|---|
| shard_core version (pyproject.toml + this repo's compose tag, together) | maintainer, in this repo | `just set-version <x.y.z>` (commits automatically — justfile:26) |
| `ghcr.io/freeshardbase/freeshard:<tag>` image | GitHub Release on this repo | release.yml verifies the release tag matches the code version, then builds/pushes |
| web-terminal image | GitHub Release on web-terminal (independent release cycle) | its own CI |
| Fleet pins (what customers run) | **controller repo only** — a new `core-versions/vN/` directory, rolled out by the controller | See freeshard-change-control. Merged-is-not-shipped: a fix on main is invisible to the fleet until (a) a version bump + GitHub Release here AND (b) a new controller core version pins it — the gap is a real incident (https://github.com/FreeshardBase/freeshard/issues/111) |

Never infer release state from a local checkout — `git fetch` and check `origin/main` + published releases first (a redundant version-bump PR was opened exactly this way: closed-unmerged PR https://github.com/FreeshardBase/freeshard/pull/113).

## 9. Pricing duplication invariant

The subscription price formula is **manually duplicated in six places across three repos** plus the canonical site. Formula (gross EUR/month, incl. 19% German VAT):

```
price_eur = (vm_base + disk_gb * 0.04) * 1.5 * 1.19
cents     = int(price_eur * 100 + 0.5)        # half-up — NEVER Python round()
```

VM base net EUR/mo: xs 5.50, s 11.00, m 19.80, l 51.00, xl 102.00.

| # | Site | File |
|---|---|---|
| 1 | **Canonical** | `freeshard-controller-backend/freeshard_controller/service/pricing.py:20` |
| 2 | Controller test | `freeshard-controller-backend/tests/test_pricing.py` |
| 3 | Controller test | `freeshard-controller-backend/tests/test_paypal_webhook.py` |
| 4 | web-terminal | `web-terminal/src/lib/pricing.js` (labels the Subscribe button only; active subscribers render controller-supplied `price_cents` — grandfathered) |
| 5 | web-terminal spec | `web-terminal/tests/unit/pricing.spec.js` |
| 6 | Landing page | `landing-page/src/components/Pricing.astro:90-115` |

Change all six together, and recompute pinned test values from the real function — don't hand-edit expected numbers. Rounding must be bit-identical between Python `int(x*100+0.5)` and JS `Math.round(x*100)`: Python's `round()` is banker's rounding and diverged from JS by 1 cent on half-cent results in production (UI label vs PayPal charge) — the comment block in pricing.py:22-24 is the standing warning.

## 10. Cross-repo gotchas (quick table)

| Gotcha | Detail |
|---|---|
| `gh issue view N --comments` fails on this org | GraphQL "Projects (classic) is being deprecated" — use `gh issue view N --repo FreeshardBase/freeshard --json body,comments` |
| Controller repo has dual CI | Both `.gitlab-ci.yml` (leftover) and GitHub Actions exist there — check which gates before trusting green |
| Two VM-size enums by design-debt | shard_core `VMSize` (app_meta.py:47, lowercase) vs copied `VmSize` (backend/shard_model.py); `Profile.from_shard` converts via `.value.lower()` (profile.py:38); a `# todo` at app_meta.py:48 tracks unification — don't half-fix it in passing |
| get-types after controller adds a module with controller-only deps | The copy is everything-or-nothing; run `pytest` (or at least `python -c "import shard_core.app"`) after every sync |

## When NOT to use this skill

- Identity crypto / signature / forwardAuth **theory** and how JWT pairing works → **freeshard-domain-reference**.
- Deciding whether a cross-repo change is allowed, release gates, "merged is not shipped" procedure → **freeshard-change-control**.
- Actually cutting a release, running the stack, first start → **freeshard-run-and-operate**.
- Recreating the dev environment, worktrees, uv → **freeshard-build-and-env** (it covers running `get-types` as environment setup; this skill covers *when and why*).
- Debugging a live cross-repo failure (422s on proxied writes, profile not refreshing) → **freeshard-debugging-playbook**; past investigations → **freeshard-failure-archaeology**.
- Config keys and env overrides (e.g. the dead `[portal_controller]` section) → **freeshard-config-and-flags**.
- Running the drift-check script and other measurement tools → **freeshard-diagnostics-and-tooling** (script lives there; this skill only points at it).

## Provenance and maintenance

Written 2026-07-03 against freeshard origin/main (`0a40684`), local sibling checkouts, and FreeshardBase remotes via `gh api`. Primary sources: `justfile`, `shard_core/service/{signed_call,portal_controller,freeshard_controller,telemetry,app_usage_reporting}.py`, `shard_core/data_model/{profile,app_meta}.py`, `shard_core/web/protected/management.py`, `shard_core/web/internal/{auth,call_backend}.py`, sibling repos' source as cited inline, PRs/issues https://github.com/FreeshardBase/freeshard/pull/102, /pull/94, /pull/112, /pull/113, /issues/93, /issues/111, commits `6d4b101`, `e55ce51`, `e78862d`.

Drift-prone facts — re-verify before relying:

| Fact (as of 2026-07-03) | Re-verification command (repo root) |
|---|---|
| Backend-copy drift state (section 3 table) | `.claude/skills/freeshard-diagnostics-and-tooling/scripts/check-type-drift.sh` |
| Local controller checkout freshness | `cd ../freeshard-controller && git fetch && git log --oneline main..origin/main` |
| Repo compose pins (shard_core 0.39.4, web-terminal 0.37.4, traefik v3.6) | `git fetch && git show origin/main:docker-compose.yml \| grep image:` |
| Fleet pins / latest core version (v18: traefik v2.11, web-terminal 0.39.4) | `gh api "repos/FreeshardBase/freeshard-controller/contents/freeshard-controller-backend/data/core-versions?ref=main" --jq '.[].name' \| sort -V \| tail -1` then fetch that version's docker-compose.yml the same way |
| Latest releases | `gh release view --repo FreeshardBase/freeshard --json tagName` (same for web-terminal) |
| Pricing formula + six duplication sites | `grep -n "0.04" ../freeshard-controller/freeshard-controller-backend/freeshard_controller/service/pricing.py ../web-terminal/src/lib/pricing.js ../landing-page/src/components/Pricing.astro` |
| AppMeta CURRENT_VERSION ("1.2") | `grep -n CURRENT_VERSION shard_core/data_model/app_meta.py` |
| Management pass-through still drops Content-Type/query | `grep -n "content" shard_core/web/protected/management.py` (empty = still drops) |
| web-terminal main no longer reads `approval_url` (SDK flow reads `plan_id`) | `git -C ../web-terminal fetch && git -C ../web-terminal grep -n 'approval_url\|plan_id' origin/main -- src/` (never grep the local working tree — it has been 15 commits stale before) |
| Email relay rate limit (10/hr) | `grep -n relay_rate_limit_per_hour ../freeshard-controller/freeshard-controller-backend/freeshard_controller/settings.py` |
| No CI enforcement of get-types | `grep -rn get-types .github/workflows/` (empty = still unenforced) |
| `management.api_url` still legacy Azure Functions default | `grep -n api_url config.toml` |
