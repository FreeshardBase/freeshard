---
name: freeshard-run-and-operate
description: "Running, deploying, and operating shard_core. Use when you need to start the app (dev server or full docker compose stack), pair a first device, find where data lands on disk (FREESHARD_DIR/core, user_data, postgres_data), run or restore a backup, cut a release, or understand hosted-vs-self-hosted behavior. TRIGGER on: 'just run-dev', 'docker compose up', .env / .env.template, pairing code, welcome log, FREESHARD_DIR, rclone / backup / restore / download_backup.sh, 'just set-version', release checklist, ghcr.io image tags, 'is this fix deployed?', self-hosting, Let's Encrypt / DISABLE_SSL. SKIP when: editing config values or env-override mechanics (use freeshard-config-and-flags), setting up the Python dev environment / uv / worktrees (use freeshard-build-and-env), writing or running tests (use freeshard-testing-and-qa), diagnosing a live failure (use freeshard-debugging-playbook), or changing CI workflows themselves (use freeshard-change-control)."
---

# Freeshard: Run and Operate

Terms used throughout (defined once):

- **shard** — one customer's personal cloud VM. Runs the 4-service Docker Compose stack in this repo.
- **shard_core** — this repo's FastAPI app. Orchestrates apps (Docker Compose per app), writes Traefik config, talks to the controller.
- **terminal** — a paired user device (browser). Pairing is the auth boundary.
- **controller** — freeshard-controller, the central cloud service at `https://controller.freeshard.net` (separate repo). Provisions hosted shards, issues backup SAS URLs, holds billing.
- **hosted shard** — a shard the controller knows about (Freeshard's fleet, on OVH). **self-hosted** — same image and compose file, but the controller returns 401 for it.
- **FREESHARD_DIR** — host directory holding all shard state (set in `.env`).

## 1. Two ways to run it

| Mode | Command | Port | Data root | Apps startable? | Auth in front? |
|---|---|---|---|---|---|
| Dev server (bare FastAPI) | `just run-dev` | 8080 | `run/` in repo | **No** (no Traefik) | **No** — all routes open |
| Full local stack | `docker compose up` | 80/443/8883 | `$FREESHARD_DIR` | Yes | Yes (Traefik forwardAuth) |

## 2. Dev server: `just run-dev`

What it does (justfile:47-48): `fastapi dev --port 8080 shard_core/app.py` with `local_config.toml` overlaying `config.toml` (that overlay is automatic whenever `local_config.toml` exists in CWD — run from repo root). Dev overrides: `path_root = "run/"`, `dns.zone = "localhost"`, debug logging (local_config.toml).

Prerequisites:

1. Python env synced (`uv sync` — see freeshard-build-and-env).
2. A reachable PostgreSQL. `[db]` defaults are host `postgres`, port 5432, db/user/password all `shard_core` (config.toml) — that hostname only resolves inside the compose network, so for bare dev supply your own and override the host:

```bash
docker run -d --name shard-dev-postgres \
  -e POSTGRES_DB=shard_core -e POSTGRES_USER=shard_core -e POSTGRES_PASSWORD=shard_core \
  -p 5432:5432 postgres:17
FREESHARD_DB__HOST=localhost just run-dev
```

(The repo documents no canonical dev-postgres recipe; the above follows from the `[db]` settings. Note the double underscore in `FREESHARD_DB__HOST` — single underscores are silently ignored; see freeshard-config-and-flags.)

Then: API docs at http://localhost:8080/docs (README.md:170). State lands in `run/` (gitignored): `run/core/`, `run/user_data/`.

Dev-server limits — know these before "testing" anything:

- **Apps cannot start.** They rely on being reached through Traefik; without the reverse proxy, app install works but app HTTP access does not (README.md:174-176).
- **No auth.** Traefik forwardAuth is the only auth layer in this system; the FastAPI routes themselves carry none. On :8080, `/protected/*` and `/management/*` are open to anyone who can reach the port.
- **It calls the production controller at startup.** `refresh_profile()` does a signed GET to `https://controller.freeshard.net/api/shards/self`; the 401/connection error is caught and logged (app_factory.py:89-92), so boot proceeds with profile = None.

### Second instance for controller development

`just run-dev-for-freeshard-controller` (justfile:50-51) starts a second shard_core on port 8081, intended to point at a locally running controller on port 8080. It sets `FREESHARD_FREESHARD_CONTROLLER__BASE_URL`. Until issue #128 that var had a single underscore before `BASE_URL`, which pydantic-settings silently ignored — the instance actually talked to the production controller. Details and the verification one-liner: freeshard-config-and-flags.


## 3. Full local stack: `docker compose up`

```bash
cp .env.template .env
# edit .env:
#   FREESHARD_DIR=/absolute/path/for/shard/data
#   DNS_ZONE=localhost          # or your real domain for a server deployment
#   EMAIL=you@example.com       # Let's Encrypt account email
#   DISABLE_SSL=true            # local testing ONLY; false in production
docker compose up
```

.env variables map to `FREESHARD_*` env vars inside the shard_core container (docker-compose.yml:63-67). `FREESHARD_DIR`, `DNS_ZONE`, `EMAIL` are fail-fast (`${VAR:?}`); `DISABLE_SSL` defaults to `false` when unset (`${DISABLE_SSL:-false}`). Until issue #128 it was unguarded, and leaving it out of `.env` crashed Settings() on an empty-string boolean (see freeshard-config-and-flags).

The stack (docker-compose.yml, all on one docker network named `portal`):

| Service | Image (origin/main as of 2026-07-03) | Role |
|---|---|---|
| postgres | postgres:17 | DB; data bind-mounted at `${FREESHARD_DIR}/postgres_data` |
| shard_core | ghcr.io/freeshardbase/freeshard:0.39.4 | this repo; waits for postgres healthy |
| traefik | traefik:v3.6 | reverse proxy, ports 80/443/8883; waits for shard_core **healthy** (shard_core writes traefik's static config before it starts) |
| web-terminal | ghcr.io/freeshardbase/web-terminal:0.37.4 | Vue UI |

### First contact: the welcome log and pairing

On every startup shard_core prints an ASCII logo block to its stdout with the shard URL; **on first start only** (terminals table empty) it also contains a pairing link valid for 10 minutes (app_factory.py:160-181):

```bash
docker compose logs shard_core | grep -A5 -B25 "pair?code"
# → https://<6-char-id>.<DNS_ZONE>/#/pair?code=XXXXXX
```

Missed the window? Get a fresh pairing code any time from inside the docker network (README.md:125):

```bash
docker run --rm -it --network portal curlimages/curl "http://shard_core/protected/terminals/pairing-code"
```

This works because auth is enforced only by Traefik forwardAuth — requests inside the `portal` network hit shard_core's port 80 directly and bypass all auth **by design**. Never publish shard_core's port to the host. (Route: GET `/protected/terminals/pairing-code`, web/protected/terminals.py:68; default validity 600 s.)

### Self-hosting with real SSL (server deployment)

Wildcard certs require a Let's Encrypt **DNS challenge**. Two changes, and the README only documents the first (README.md:138-154):

1. Add your DNS provider's env vars to the **traefik** service in docker-compose.yml (the commented-out `AZURE_*` block at lines 38-42 is the template).
2. The ACME `provider` is **hardcoded to `azure`** in the traefik static-config template `data/traefik.yml:40` (in-image). shard_core re-renders `${FREESHARD_DIR}/core/traefik.yml` from that template **on every startup** (app_factory.py:140-157), so editing the rendered file does not stick — for a non-Azure DNS provider you must change `data/traefik.yml` and rebuild the image (or bind-mount a patched copy over `/app/data/traefik.yml`). (Bind-mount approach unverified as of 2026-07-03.)

## 4. What lands where on disk

Everything below `FREESHARD_DIR` on the host; the same tree is `/` inside the container (`path_root`). Rule: `path_root` for anything shard_core reads/writes itself; `path_root_host` only for volume paths rendered into app compose templates (host docker daemon resolves those) — see freeshard-architecture-contract.

| Path (host) | Contents | Written by |
|---|---|---|
| `$FREESHARD_DIR/core/traefik.yml` | Traefik static config | rendered at every shard_core start (app_factory.py:140-157) |
| `$FREESHARD_DIR/core/traefik_dyn/traefik_dyn.yml` | per-app routers + forwardAuth middlewares | startup and every app (un)install |
| `$FREESHARD_DIR/core/acme.json` | Let's Encrypt state | traefik |
| `$FREESHARD_DIR/core/installed_apps/<name>/` | app's docker-compose.yml + template + assets | app installation |
| `$FREESHARD_DIR/user_data/app_data/<name>/` | app's persistent data | apps |
| `$FREESHARD_DIR/user_data/shared/` | cross-app shared files | apps |
| `$FREESHARD_DIR/postgres_data/` | **the database**: identities (private keys!), terminals, installed_apps, kv_store, backups | postgres container |

Operational threshold: a background task measures free space on `{path_root}/user_data` every 30 s; **below 1 GiB free, ALL apps are stopped** (disk.py:22-30, app_lifecycle).

## 5. First-start behavior (idempotence rules)

On a fresh `FREESHARD_DIR` + empty DB, the lifespan (app_factory.py:78-99) does, in order:

1. yoyo migrations + DB pool + one-time TinyDB→Postgres import (if a pre-0.38 `core/shard_core_db.json` exists, it is imported and renamed `.json.backup` — database/tinydb_migration.py).
2. **Identity generation**: if the identities table is empty, creates the default identity — RSA-4096 key (agents.md wrongly says Ed25519; the code is RSA-PSS, shard_core/service/crypto.py). Shard domain = first 6 chars of the identity id, lowercased, + `.` + `dns.zone` (data_model/identity.py:59-64). **The domain is derived from the key** — lose the DB, lose the identity and the domain.
3. Traefik dyn config, app compose re-render, `docker login` for registries.
4. **initial_apps install** — `filebrowser`, `immich`, `paperless-ngx` (config.toml `[apps] initial_apps`) are queue-installed **on first boot only**, guarded by kv_store flag `initial_apps_installed` (app_installation/__init__.py:102-120). Deleting one later does not resurrect it on restart.
5. Backup passphrase: 10-word EFF-wordlist passphrase generated into kv_store key `backup_passphrase` if absent (backup.py:203-212).
6. Profile refresh (failure-tolerant), background tasks start, welcome log prints.

## 6. Backup operations

### How production backup works

- **Trigger**: CronTask `0 3 * * *` (container time, UTC in practice) plus a random delay of up to 3600 s (config.toml `[services.backup.timing]`), or manually via POST `/protected/backup/start`.
- **Flow**: shard asks the controller for an Azure SAS URL (`GET api/shard_backup/backup_sas_url`, service/portal_controller.py:39-42) → rclone **crypt** sync of `core/` and `user_data/` (config.toml `directories`) to `:crypt:{container}/{dir}` on Azure Blob, encrypted with the kv_store passphrase → `BackupReport` row in the `backups` table → a `_last_backup` marker blob is uploaded; its Last-Modified timestamp is the recency signal the controller monitors (backup.py).
- rclone flags as of 2026-07-03: `--fast-list` yes; `--azureblob-no-check-container` was added for Azure-cost reasons (PR https://github.com/FreeshardBase/freeshard/pull/106) then **removed** because the fleet's rclone didn't support it and all v18 backups failed (https://github.com/FreeshardBase/freeshard/issues/117, fix PR https://github.com/FreeshardBase/freeshard/pull/119). Check `COMMAND_TEMPLATE` in shard_core/service/backup.py before assuming flags.
- **Self-hosted shards cannot back up, by design**: no controller profile → no SAS URL → `BackupStartFailedError` (backup.py:57-60). Self-hosters must snapshot `$FREESHARD_DIR` themselves.
- **Passphrase retrieval** (needed for any restore): GET `/protected/backup/passphrase` — externally `https://<shard-domain>/core/protected/backup/passphrase` from a paired terminal, or from inside the docker network:

```bash
docker run --rm -it --network portal curlimages/curl \
  -H "X-Ptl-Client-Id: cli" "http://shard_core/protected/backup/passphrase"
```

  (The header is required — 400 without; every access is recorded in kv_store, web/protected/backup.py:50-55.)

### THE backup gap: Postgres is not in it

The backup set is `['core', 'user_data']` only. `postgres_data/` is a sibling directory and is **not backed up** — and since the 0.38.0 TinyDB→Postgres migration, identities (private keys), terminals, installed-app rows, and the backup passphrase itself live only in Postgres. **A backup taken by any release >= 0.38.0 cannot restore a shard's identity.** Open issue: https://github.com/FreeshardBase/freeshard/issues/122. Pre-0.38 backups still contain `core/shard_core_db.json`, which auto-imports on first boot. Whether hosted infra separately snapshots `postgres_data` is a controller-side question — not answerable from this repo.

### Restore-for-debugging runbook (run a customer backup locally)

1. Get the shard's backup container name, a read SAS URL (controller-side), and the passphrase (route above, or ask the owner).
2. Fill the three variables at the top of `download_backup.sh` (repo root) and run it — it rclone-decrypts the whole container into `./$CONTAINER/` (containing `core/` and `user_data/`).
3. Zip it so `core/` and `user_data/` sit at the zip root, then load it into the dev data dir:

```bash
(cd "$CONTAINER" && zip -r ../backup.zip core user_data)
just run-from-backup backup.zip   # rm -rf run && unzip into run/
just run-dev                      # dev server now runs against the restored files
```

(`run-from-backup`: justfile:9-11. The zip step is not documented in-repo; the layout requirement follows from `path_root = "run/"`.)

4. Expect a **fresh** identity/DB: the restored files contain no Postgres state (gap above), so the dev instance generates a new identity and the restored `installed_apps/` rows won't exist in its DB.

## 7. Release checklist

**This checklist is the maintainer's.** Agents: at most prepare a version-bump PR when explicitly asked (after fetching — see freeshard-change-control §5); never push to main, never publish a Release.

Versioning is a linear X.Y.Z sequence today; migration to real semver is decided in principle but not implemented (https://github.com/FreeshardBase/freeshard/issues/118, open as of 2026-07-03).

1. **Sync first — never version-bump from a stale checkout**:
   ```bash
   git fetch origin && git checkout main && git pull
   grep '^version' pyproject.toml   # confirm current version before choosing the next
   ```
2. `just set-version X.Y.Z` — rewrites `version` in pyproject.toml **and** the `ghcr.io/freeshardbase/freeshard:` tag in docker-compose.yml, then commits "set version to X.Y.Z" (justfile:25-45; needs `.venv`).
3. `git push`
4. Create a GitHub Release whose **tag is exactly `X.Y.Z`** (e.g. `gh release create X.Y.Z --title X.Y.Z --generate-notes`). The Release event drives `.github/workflows/release.yml`: a version-check job fails the build if tag != pyproject version ("Run 'just set-version' and commit first"), then the full test workflow, then buildx pushes `ghcr.io/freeshardbase/freeshard:X.Y.Z`.
5. **Fleet rollout is a separate, controller-side step.** Hosted shards run the pinned tag from their compose file; rolling the fleet means a core-version/compose bump in the freeshard-controller repo (see freeshard-ecosystem-contracts). Nothing in this repo deploys anything.

**MERGED IS NOT SHIPPED.** Every push already publishes a snapshot image tagged with the branch slug (`.github/workflows/snapshot.yml`, e.g. `ghcr.io/freeshardbase/freeshard:main`), but production shards only ever run **release tags**. Incident: the fd-leak fix (PR https://github.com/FreeshardBase/freeshard/pull/108) was merged while shards kept failing, because no release tag contained it — tracked as https://github.com/FreeshardBase/freeshard/issues/111, resolved by releasing 0.39.4 (2026-06-24). When asked "is fix X live?", the answer requires: (a) merged to main, (b) contained in a release tag (`git tag --contains <sha>`), AND (c) that tag rolled out by the controller.

Release gating and what may ship at all: freeshard-change-control. This checklist is mechanics only.

## 8. Hosted vs self-hosted differences

Same image, same compose file. The only fork is whether `GET {controller}/api/shards/self` recognizes the shard's signature (401 → `profile = None`, service/portal_controller.py:21-36).

| Axis | Hosted (fleet) | Self-hosted |
|---|---|---|
| Controller profile | populated from controller | `None` |
| VM-size gates on app install | enforced (`profile.vm_size` vs app `minimum_portal_size`) | **none** — `size_is_compatible()` returns True when profile is None (app_tools.py:141-149) |
| Backups | daily rclone crypt to Azure via controller SAS URL | **fail by design** (`BackupStartFailedError`) — bring your own `$FREESHARD_DIR` snapshot |
| Management API (`/management`: install apps, notify, pairing-code) | called by controller, authed via shared secret forwardAuth | inert (nobody holds the secret) |
| SSL | wildcard via DNS-01, Azure DNS creds provided by fleet tooling | must add provider env vars **and** patch the hardcoded `provider: azure` (section 3) |
| DNS zone | `freeshard.cloud` (config.toml default) | `DNS_ZONE` in `.env` |
| Billing/resize passthrough (`/protected/management/{rest}`) | proxies signed requests to controller | returns controller 401s |

## 9. Production ops invariants (fleet knowledge)

Operational rules learned in production, stated here so nobody relearns them (fleet-side facts; not verifiable from this repo alone):

- **`docker daemon.json` changes to `log-driver`/`log-opts`/`default-ulimits` require `systemctl restart docker`, not `reload`.** SIGHUP reloads only a whitelisted subset; containers keep stale in-memory values even when recreated after a reload. Restart bounces all containers — schedule it in a maintenance window. Fleet default logging: json-file, max-size 10m, max-file 3.
- **Hosted shards run on OVH** (as of 2026-07-03; Azure is EOL for shard VMs).
- **Pin LTS base images only.** OVH rotated out a non-LTS Ubuntu image without notice and broke provisioning; interim releases die in months.
- **Traefik entrypoints must keep a finite `readTimeout`** (`300s` in data/traefik.yml on main). readTimeout=0 plus internet scanners = fd leak → EMFILE → shard "Up" but unreachable (PR https://github.com/FreeshardBase/freeshard/pull/108). Don't remove it when touching the template.
- **Keep >1 GiB free on the user_data volume** — below that, shard_core stops all apps (section 4).

## 10. When NOT to use this skill

| You are trying to… | Use instead |
|---|---|
| Add/change a config option, understand env overrides, `FREESHARD_*` vars | freeshard-config-and-flags |
| Set up Python env, uv, worktrees, type-sync from controller | freeshard-build-and-env |
| Run or write tests, interpret CI test failures | freeshard-testing-and-qa |
| Debug a misbehaving shard or app (symptom → cause) | freeshard-debugging-playbook |
| Decide whether a change may ship, review gates, release policy | freeshard-change-control |
| Understand crypto/signatures/forwardAuth/backup theory | freeshard-domain-reference |
| Cross-repo contracts (controller compose bump, web-terminal, app-repository) | freeshard-ecosystem-contracts |
| Why the architecture is shaped this way; invariants | freeshard-architecture-contract |
| Measure performance / run diagnostic scripts | freeshard-diagnostics-and-tooling |

## Provenance and maintenance

Written 2026-07-03 against origin/main `0a40684` (version 0.39.4). Primary sources: justfile, docker-compose.yml, .env.template, README.md (Hosting/Development sections), shard_core/app_factory.py, shard_core/service/{backup,portal_controller,disk,identity,app_tools}.py, shard_core/web/protected/{backup,terminals}.py, data/traefik.yml, download_backup.sh, .github/workflows/{release,snapshot}.yml, config.toml, local_config.toml; GitHub issues/PRs #106, #108, #111, #117, #118, #119, #122.

Note: the working tree you find yourself in may be a stale branch — verify volatile facts against `origin/main`, not the checkout.

Drift-prone facts — re-verify before relying on them:

| Fact (as of 2026-07-03) | Re-verify with |
|---|---|
| Latest release = 0.39.4 | `gh release list --limit 1` |
| Compose pins freeshard:0.39.4, traefik:v3.6, web-terminal:0.37.4, postgres:17 | `git show origin/main:docker-compose.yml \| grep image:` |
| ACME provider hardcoded `azure`; readTimeout 300s | `git show origin/main:data/traefik.yml \| grep -n 'provider\|readTimeout'` |
| Backup dirs = core, user_data (no postgres_data) | `grep -A1 '\[services.backup\]' config.toml` |
| rclone flags (`--fast-list`, no `--azureblob-no-check-container`) | `git show origin/main:shard_core/service/backup.py \| grep -A9 '^COMMAND_TEMPLATE'` |
| initial_apps = filebrowser, immich, paperless-ngx | `grep initial_apps config.toml` |
| Backup cron 03:00 + ≤3600s jitter | `grep -A2 'backup.timing' config.toml` |
| Postgres-not-in-backup still open | `gh issue view 122 --json state` |
| Semver migration still pending | `gh issue view 118 --json state` |
| run-dev-for-freeshard-controller env var still uses the double `_` | `grep FREESHARD_FREESHARD_CONTROLLER justfile` (broken if not `CONTROLLER__BASE_URL`) |
| Release tag==version gate exists | `grep -n 'does not match pyproject' .github/workflows/release.yml` |
| Pairing route + 10-min first-start code | `grep -n 'pairing-code' shard_core/web/protected/terminals.py; grep -n '10 \* 60' shard_core/app_factory.py` |
