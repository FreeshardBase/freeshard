---
name: freeshard-architecture-contract
description: Load-bearing design decisions, invariants, and honest weak points of shard_core. Use BEFORE changing anything that touches auth, routing, startup/shutdown order, app status handling, signals, caching, or paths. TRIGGER on "why is there no auth on this route", "add an endpoint", "add a status", "app not starting", edits to app_factory.py, web/internal/auth.py, traefik_dynamic_config.py, app_tools.py, app_lifecycle.py, signals.py, or any question about path_root vs path_root_host, JWT, forwardAuth, or what survives a restart. SKIP for step-by-step how-to-run instructions (use freeshard-run-and-operate), config option catalogs (use freeshard-config-and-flags), protocol theory (use freeshard-domain-reference), or debugging a live symptom (use freeshard-debugging-playbook).
---

# Freeshard Architecture Contract

The invariants that hold shard_core together, and the places where it is honestly weak.
shard_core is the FastAPI app that runs on every "shard" (a personal cloud VM). It sits
behind a Traefik reverse proxy, drives sibling Docker containers ("apps") through the
mounted docker socket, and stores state in PostgreSQL. Everything below is verified
against the repo as of 2026-07-03 (branch state: v0.39.2 era).

## 1. The auth model: FastAPI has ZERO auth — Traefik is the gate

**No route handler in `shard_core/web/` carries any auth dependency.** There is no
`Depends(get_current_user)` anywhere. Enforcement is 100% (a) Traefik forwardAuth
middlewares and (b) Docker network topology. This is the single most important fact
about this codebase: an endpoint's security is defined by the Traefik router that fronts
it, not by its code.

`create_app()` mounts exactly four routers (shard_core/app_factory.py:59-62), with
prefixes from each package's `__init__.py`: `/internal`, `/public`, `/protected`,
`/management`. Traefik's dynamic config is compiled in Python
(shard_core/service/traefik_dynamic_config.py) — external paths `/core/<level>/...`
have the `/core/` prefix stripped by the `strip` middleware
(traefik_dynamic_config.py:82-85) before reaching FastAPI.

### The four auth levels

| External route | FastAPI prefix | Traefik middlewares | Enforcement |
|---|---|---|---|
| `/core/public/...` | `/public` | `strip`, `auth-public` | NONE. `auth-public` only injects request headers `X-Ptl-Client-Type: public` (+ empty Id/Name) (traefik_dynamic_config.py:106-116) |
| `/core/protected/...` | `/protected` | `strip`, `auth-private` | forwardAuth → `http://shard_core/internal/authenticate_terminal`: verifies the `authorization` cookie JWT, sets `X-Ptl-Client-{Type,Id,Name}` response headers which Traefik copies onto the request (traefik_dynamic_config.py:87-98; web/internal/auth.py:47-60) |
| `/core/management/...` | `/management` | `strip`, `auth-management` | forwardAuth → `http://shard_core/internal/authenticate_management`: `authorization` header must equal the controller shared secret in kv_store key `freeshard_controller_shared_key` (min length 8; on miss/mismatch it re-fetches once from the controller via signed `GET api/shards/self`) (web/internal/auth.py:63-71; service/freeshard_controller.py:28-44) |
| `https://<app>.<domain>/...` (app subdomains) | n/a (proxied to app container) | `app-error`, `auth` | forwardAuth → `http://shard_core/internal/auth` with `authResponseHeadersRegex: ^X-Ptl-.*` (traefik_dynamic_config.py:117-124) — see AuthState below |
| (not routed) | `/internal` | — | **Unauthenticated by design.** Never routed by Traefik; reachable only inside the `portal` docker network |

### App-subdomain auth (`GET /internal/auth`, web/internal/auth.py:74-179)

Per request to any app, Traefik asks shard_core:

1. Match app by first label of `X-Forwarded-Host` against `installed_apps` (cached, see §6). Unknown app → 404.
2. Longest-prefix match of `X-Forwarded-Uri` against the app's `app_meta.json` paths.
3. Compute `AuthState`: valid terminal JWT cookie → `TERMINAL`; else valid RSA HTTP Message Signature (reconstructed from `X-Forwarded-Method/Proto/Host/Uri` headers, service/peer.py:79-106) → `PEER`; else `ANONYMOUS`.
4. Deny 401 if path access is `private` without TERMINAL, or `peer` without PEER (auth.py:88-100).
5. Render the path's per-header jinja2 templates with `auth` + `portal` values into response headers; fire `on_request_to_app` (auth.py:102-111) — this signal is what starts idle apps.

Known sharp edge: `_match_path` returns `None` when no path prefix matches, and the
caller immediately does `path_object.access` → `AttributeError` → 500 from the
forwardAuth endpoint (auth.py:82-83, 141-147).

### KNOWN WEAKNESS — state it plainly, design around it

Every installed app container joins the same external docker network `portal` as
shard_core (see tests/mock_app_store/mock_app/docker-compose.yml.template:1-3,16-17).
shard_core serves plain HTTP on container port 80 with no in-app auth, so **any app
container can `curl http://shard_core/protected/...` or `/management/...` or
`/internal/...` directly, bypassing all auth**. Consequences you must respect:

- **Never publish shard_core's port** in docker-compose.yml (it currently has no `ports:` — keep it that way; only Traefik publishes 80/443/8883).
- **Treat every new endpoint — any router — as app-reachable.** Do not put secrets or destructive operations behind "protected" and assume only the owner can call them; a malicious app can.
- Header-trusting endpoints inherit this: e.g. `GET /protected/backup/passphrase` trusts the `X-Ptl-Client-Id` request header (web/protected/backup.py), which is only trustworthy when injected by Traefik.
- The Traefik dashboard runs with `api.insecure: true` (data/traefik.yml) and is likewise reachable unauthenticated from inside the network; its external route `traefik.<domain>` is gated by `auth-private` (traefik_dynamic_config.py:72-78).

This is a known accepted-for-now risk, not an invitation. Nothing in the repo mitigates
it as of 2026-07-03; if your change widens the blast radius (new secret-returning
endpoint, new mutating internal route), flag it in the PR.

## 2. Identity and session crypto

**The signing scheme is RSA, not Ed25519.** agents.md claimed Ed25519 until issue #128
corrected it; if you meet that claim anywhere else, the code wins.

- Keys: RSA-4096, exponent 65537 (shard_core/service/crypto.py:52-57). Raw sign/verify uses PSS padding with MGF1(SHA256)+SHA256 (crypto.py:34-46,79-86).
- Identity id = human-encoded SHA512 of the public key PEM (crypto.py:29-32). The encoding is 5-bits-per-char over the 32-char alphabet `abcdefghjklnpqrstvwxyz0123456789` (shard_core/service/human_encoding.py:102), giving a **103-char id** (512 bits / 5, zero-padded — verified by computation; some docs say 96, that is wrong).
- `short_id` = first 6 chars of id (data_model/identity.py:46-47). Shard domain = `id[:dns.prefix_length].lower() + "." + dns.zone` with `prefix_length = 6` (identity.py:58-64) — so the domain is derived from the key hash.
- Outgoing signed calls: IETF HTTP Message Signatures, `RSA_PSS_SHA512`, `key_id = short_id`, executed via `asyncio.to_thread(requests.request, ...)` (service/signed_call.py:14-30). Incoming peer verification resolves the signer by `keyid` = peer short_id prefix (peer.py:101-106).

**Terminal JWTs (the browser session): HS256, and there is NO `exp` claim.** Payload is
`{sub: terminal_id, iat}` only (service/pairing.py:59-66). The secret is auto-generated
(`secrets.token_urlsafe(64)`) and stored in kv_store key `terminal_jwt_secret`
(pairing.py:92-98). **Revocation = deleting the terminal row**: `verify_terminal_jwt`
looks up the terminal by `sub` and rejects if the row is gone (pairing.py:84-89). The
cookie is named `authorization`, httponly+secure, scoped to the shard domain, expiry
~10 years (web/public/pair.py:42-49 — note the `356`-day typo, harmless). Invariant: if
you ever add a second way to mint terminal JWTs, it must keep the row-existence check as
the revocation mechanism, or add `exp` properly.

## 3. Startup and shutdown order (app_factory.py) — a real contract

Two phases. Phase 0 runs at import/`create_app()` time, BEFORE the lifespan:

- `_copy_traefik_static_config()` renders `data/traefik.yml` (or `traefik_no_ssl.yml`) to `{path_root}/core/traefik.yml` (app_factory.py:46-49, 140-157). This resolves the traefik↔shard_core dependency cycle: Traefik's compose service has `depends_on: shard_core: service_healthy`, so the static config exists before Traefik boots (docker-compose.yml:48-50).

Phase 1, the lifespan (app_factory.py:78-108), in order — each step depends on the previous:

| # | Step | Why it must come here |
|---|---|---|
| 1 | `database.init_database()` — sync yoyo `migrate()`, open psycopg pool (max_size=20), one-time TinyDB→Postgres import (database/database.py:26-34) | Everything else reads the DB |
| 2 | `identity.init_default_identity()` — create RSA-4096 default identity if table empty | Steps 3-4 render identity values |
| 3 | `write_traefik_dyn_config()` — compile per-app routers to `{path_root}/core/traefik_dyn/traefik_dyn.yml` (app_installation/util.py:103-124) | Needs DB + identity |
| 4 | `render_all_docker_compose_templates()` — re-render every installed app's compose file from its `.template` (util.py:65-75) | Needs identity; must precede any app start |
| 5 | `login_docker_registries()` (app_installation/__init__.py:123-133, errors logged not raised) | Before any image pull |
| 6 | `migration.migrate()` — legacy no-op stub (service/migration.py) | — |
| 7 | `refresh_init_apps()` — first-boot-only ENQUEUE of `apps.initial_apps`, guarded by kv flag `initial_apps_installed` (__init__.py:102-120) | Enqueue only — see deadlock warning |
| 8 | `ensure_backup_passphrase()` — generate + store passphrase if absent (backup.py:203-212) | — |
| 9 | `portal_controller.refresh_profile()` wrapped in `try/except (ConnectionError, HTTPError, ValidationError)` (app_factory.py:89-92) | Failure tolerated so self-hosted shards (no controller) still boot. The caught types are `requests` exceptions — swapping the HTTP client under `signed_request` would turn controller outages into boot loops |
| 10 | Start background tasks (app_factory.py:94-96) — **the InstallationWorker starts only HERE** | See deadlock warning |
| 11 | `print_welcome_log()` — prints shard URL + first-boot pairing link | — |

**DEADLOCK WARNING:** between steps 7 and 10, installation tasks are queued but nothing
consumes them. Code inserted in the lifespan must never await installation
completion before step 10 — it will hang forever. Enqueue is fine; awaiting results is not.

Shutdown (app_factory.py:101-108): stop all background tasks → await them →
`docker_shutdown_all_apps(force=True)` (compose `down` for every app, status → DOWN) →
close the DB pool. The compose file's `stop_grace_period: 30s` on shard_core
(docker-compose.yml:56) exists to let this finish; long-running additions to shutdown
must fit inside that budget or raise it.

## 4. App Status state machine — "adding a status? audit all six"

`Status` enum (data_model/app_meta.py:29-40): UNKNOWN, INSTALLATION_QUEUED, INSTALLING,
STOPPED, RUNNING, UNINSTALLATION_QUEUED, UNINSTALLING, REINSTALLATION_QUEUED,
REINSTALLING, DOWN, ERROR. (`InstalledApp.status` is typed plain `str`, app_meta.py:147
— the DB column holds the string values.)

Transitions as implemented (single serial in-memory queue, one worker,
app_installation/worker.py):

- install: row inserted as INSTALLATION_QUEUED → worker asserts it (worker.py:98,111) → INSTALLING → STOPPED on success | ERROR on failure
- reinstall: any → REINSTALLATION_QUEUED (no precondition) → worker asserts (worker.py:148) → REINSTALLING → STOPPED | ERROR
- uninstall: any → UNINSTALLATION_QUEUED → UNINSTALLING (**no status assertion**, worker.py:124-128) → row deleted
- ERROR is escaped only via uninstall or reinstall

The four status **allow-lists** live in shard_core/service/app_tools.py:

| Function | Acts only when status in | Line |
|---|---|---|
| `docker_start_app` | STOPPED, RUNNING, DOWN | app_tools.py:36 |
| `docker_stop_app` | RUNNING, UNINSTALLING | app_tools.py:76 |
| `docker_shutdown_app` | STOPPED, UNINSTALLING (or `force=True`) | app_tools.py:92 |
| worker asserts | INSTALLATION_QUEUED / REINSTALLATION_QUEUED | worker.py:98,111,148 |

Plus two **exclusion filters**:

- `write_traefik_dyn_config` skips INSTALLATION_QUEUED and ERROR apps (app_installation/util.py:108,113)
- `control_apps` (idle lifecycle) skips INSTALLATION_QUEUED and INSTALLING (service/app_lifecycle.py:45)

**RULE: when adding or repurposing a status, audit all six sites above.** A status
missing from an allow-list silently no-ops (`log.debug` + skip); a status missing from
the exclusion filters gets routed/lifecycled while half-installed —
`write_traefik_dyn_config` calling `get_app_metadata()` on an app with missing files
raises `MetadataNotFound` inside the lifespan (app_factory.py:83) → potential boot loop.

## 5. Signals discipline (shard_core/util/signals.py, blinker)

Two invariants, both currently honored — preserve them:

1. **Sync/async pairing.** Signals fired with `.send()` (`on_backup_update`, `on_disk_usage_update`, `on_terminal_add`, `on_app_install_error`, `on_peer_auth`) have only sync receivers; signals fired with `await ....send_async()` (`on_apps_update`, `on_terminals_update`, `on_terminal_auth`, `on_request_to_app`, `on_identity_update`, `async_on_first_terminal_add`, `async_on_peer_write`) have async receivers. An async receiver on a sync-sent signal produces a silently un-awaited coroutine — no error, no effect.
2. **Every `installed_apps` status write must be followed by `await signals.on_apps_update.send_async()`.** Its two receivers are `websocket.send_apps_update` (UI push, service/websocket.py:131) and `auth._invalidate_app_cache` (web/internal/auth.py:42-44). Forgetting it means the forwardAuth endpoint serves **stale auth decisions** (including cached negative lookups → 404s for a freshly installed app) until an unrelated update fires. All existing write paths comply (app_tools.py:67,83,99; app_installation/util.py:54; worker.py:142,172; __init__.py:41,64,80).

Note `on_peer_auth` (auth.py:170) has zero listeners as of 2026-07-03 — dead signal,
don't build on it without wiring a receiver.

## 6. Auth-path caches exist for a reason (#89)

Traefik forwardAuth fires on **every single request** to every app. When the auth
endpoint did per-request DB lookups, request bursts exhausted the pool and produced
batches of 500s — https://github.com/FreeshardBase/freeshard/issues/89 (closed). The
fix: module-global `_identity_cache` and `_app_cache` in web/internal/auth.py:32-44
(the app cache also caches `None` for unknown names), invalidated by the
`on_identity_update` / `on_apps_update` signals, plus pool max_size=20
(database/connection.py).

**RULE: any new per-request work on the auth path (`/internal/auth`,
`/internal/authenticate_terminal`) needs a cache with signal-driven invalidation, or it
recreates #89.** Exceptions that already exist and are tolerated: `on_terminal_auth`
triggers a `terminals.last_connection` DB write per auth (data_model/terminal.py:42-50),
and `on_request_to_app` triggers a debounced `last_access` write at most every 60s
(data_model/app_meta.py:155-168). Don't add more without measuring.

## 7. Path duality: path_root vs path_root_host

Two settings that look interchangeable and are not (mixing them breaks apps):

| Setting | Meaning | Prod value | Use for |
|---|---|---|---|
| `path_root` | Path **inside the shard_core container** | `/` (so `/core`, `/user_data`) | Everything shard_core itself reads/writes: installed_apps dir, traefik configs, backup dirs, disk stats |
| `path_root_host` | Path **on the host VM** | `${FREESHARD_DIR}` via env (docker-compose.yml:67) | ONLY the `fs.*` volume paths rendered into app docker-compose templates (app_installation/util.py:80-86) |

Why: app containers are started by the **host** docker daemon (shard_core drives the
mounted docker socket), so volume paths in app compose files must be host paths, while
shard_core sees the same directories through its own bind mounts. In local dev,
`path_root = "run/"` (local_config.toml). A template rendered with `path_root` mounts a
path that doesn't exist on the host — the app starts with empty volumes.

## 8. In-memory-only state and what a restart costs

None of the following survives a process restart. Know the consequences before relying
on any of them:

| State | Location | Restart consequence |
|---|---|---|
| Installation queue | `asyncio.Queue` in `InstallationWorker` (worker.py:47) | Queued/in-flight tasks vanish; DB rows stay stranded in *_QUEUED/INSTALLING — **there is no startup reconciliation** (see §10) |
| App last-access times | `last_access_dict` (app_lifecycle.py:20) | Defaults to 0.0 → **on the first `control_apps` tick after boot, every non-always-on RUNNING app is stopped** (app_lifecycle.py:63-66). The DB `last_access` column is written (debounced) but never consulted by idle-stop — two divergent notions of last access |
| Telemetry counters | module globals `no_of_requests`, `last_send` (telemetry.py:12-13) | Counts lost (feature default-off anyway) |
| Disk usage snapshot | `disk.current_disk_usage` module global (disk.py:20) | Starts as `disk_space_low=False` until the first 30s tick |
| Backup-in-progress lock | `BACKUP_IN_PROGESS_LOCK` (backup.py:30) | A backup interrupted by restart leaves no lock — but also no record of the partial sync |
| Auth caches | `_identity_cache`, `_app_cache` (auth.py:32-33) | Cold; repopulated on demand — harmless |

If your feature needs restart-surviving state, put it in Postgres (kv_store for
scalars); do not extend these in-memory structures and assume durability.

## 9. Everything is CWD-relative — run from repo/image root only

- Config files: literal `"config.toml"` / `"local_config.toml"` paths (settings.py:139-152). Wrong CWD = all TOML config silently missing; only required-field ValidationErrors surface.
- Migrations: `Path.cwd() / "migrations"` (database/migration.py:22). Wrong CWD = yoyo finds **zero** migrations and reports success.
- `data/` assets: traefik static config template and welcome log read `Path.cwd() / "data" / ...` (app_factory.py:147,177).

In the image, WORKDIR is `/app` and this all works; in dev, `just run-dev` runs from
repo root. Never `cd` elsewhere before starting shard_core, and never "fix" a path by
absolutizing just one of these three — they move together.

## 10. Known-weak list — real, current, with receipts

State these plainly in reviews; do not paper over them, and do not silently "fix" them
inside an unrelated PR (each is its own change, gated by freeshard-change-control).
All verified 2026-07-03:

| Weakness | Evidence | Status |
|---|---|---|
| No startup reconciliation of stranded *_QUEUED / INSTALLING rows; a crash mid-install strands the row forever (manual uninstall works because `_uninstall_app` asserts nothing) | lifespan app_factory.py:78-108 has no such step; worker.py:124-128 | Open, no issue filed |
| Stranded INSTALLING/UNINSTALLING row + missing files → `MetadataNotFound` raised uncaught in lifespan step 3 → boot loop | app_installation/util.py:110-114 filters only INSTALLATION_QUEUED and ERROR | Open |
| backup.py blocks the event loop: sync `subprocess.run(["rclone","obscure",...])` (backup.py:186-188) and sync Azure `BlobClient.upload_blob` marker write (backup.py:133-151); rclone command built via `str.split()` breaks on whitespace in SAS URL/paths (backup.py:169) | file:lines cited | Open |
| Backup task is fire-and-forget with no strong reference — `task` is a local var and the done-callback spawns another unreferenced task (asyncio weak-ref GC footgun); contrast the correct `background_tasks` set pattern in app_lifecycle.py:32-36 | backup.py:62-78 | Open |
| rclone exit code never checked — success inferred from parsing the last stderr line as JSON; a failure ending in valid JSON records as success, a non-JSON last line raises `JSONDecodeError` | backup.py:168-181 | Open; known trouble spot (repeated churn: commits b9dfcfd, 935250b, d6560a0) |
| Terminal JWTs have no expiry; revocation is solely row deletion | pairing.py:59-66 | Accepted design as of 2026-07-03 (see §2) |
| Backup passphrase stored PLAINTEXT in Postgres kv_store, returned by `GET /protected/backup/passphrase` — which is app-reachable per §1 | backup.py:28,184-189,215-224 | Open |
| **Postgres data is NOT in the backup set** — backup syncs only `core/` and `user_data/` while identities (private keys!), terminals, installed_apps, kv_store live in `${FREESHARD_DIR}/postgres_data`; a restored shard loses its identity | config.toml `[services.backup] directories`; docker-compose.yml:19; https://github.com/FreeshardBase/freeshard/issues/122 (filed 2026-07-03) | Open issue |
| `@throttle(5)` on `docker_start_app` is **global across all apps**, not per-app, and silently returns None when throttled — a request to app B within 5s of app A's start doesn't start B; recovery waits for the next request or lifecycle tick | app_tools.py:30; util/misc.py:5-27 | Open |
| `peer.update_peer_meta` catches `httpx.HTTPStatusError` around a **requests** response's `raise_for_status()` — requests raises `requests.exceptions.HTTPError`, so any non-2xx peer reply escapes, propagates through `asyncio.gather` (no `return_exceptions`) and aborts the whole 60s peer-refresh cycle (saved only by PeriodicTask's catch-all) | peer.py:39-56, 29-33 | Live bug as of 2026-07-03; no open issue found |
| `update_app_status(..., message=...)` does not persist the message — ERROR reasons reach the UI only via a transient websocket event; after reload the UI shows ERROR with no cause | app_installation/util.py:45-54 | Open |
| `/internal/auth` 500s (AttributeError) when no app_meta path prefix matches the URI | web/internal/auth.py:82-83,141-147 | Open |
| Live-looking Azure Container Registry credentials committed in config.toml `[[apps.registries]]`, docker-logged-in at every boot | config.toml; app_installation/__init__.py:123-133 | Known; do not copy the pattern |

## When NOT to use this skill

- Recreating the dev environment, uv, worktrees → **freeshard-build-and-env**
- Running the stack, deploy, release, backup/restore procedure → **freeshard-run-and-operate**
- Config option catalog, env-override rules, dead config → **freeshard-config-and-flags**
- Crypto/protocol theory (HTTP Message Signatures, rclone crypt, JWT pairing in depth) → **freeshard-domain-reference**
- A live symptom to triage → **freeshard-debugging-playbook**; its history → **freeshard-failure-archaeology**
- Whether/how a change may ship at all → **freeshard-change-control** (this skill describes what IS; that one gates what may CHANGE)
- Cross-repo contracts with controller/web-terminal → **freeshard-ecosystem-contracts**

## Provenance and maintenance

Written 2026-07-03 by direct verification against the working tree at commit e55ce51
(branch fix-profile-billing-fields; identical for all files cited here unless noted).
Primary sources: shard_core/{app_factory.py, settings.py}, shard_core/web/internal/auth.py,
shard_core/service/{traefik_dynamic_config.py, crypto.py, pairing.py, peer.py, backup.py,
app_tools.py, app_lifecycle.py, telemetry.py, disk.py, freeshard_controller.py,
signed_call.py, app_installation/*}, shard_core/util/{signals.py, misc.py, async_util.py},
shard_core/database/migration.py, shard_core/data_model/{identity.py, app_meta.py},
docker-compose.yml, config.toml,
https://github.com/FreeshardBase/freeshard/issues/89,
https://github.com/FreeshardBase/freeshard/issues/122.

Drift-prone facts — re-verify before relying on them:

| Fact | Re-verification command (from repo root) |
|---|---|
| Routes still carry no FastAPI auth dependency | `grep -rn "Depends" shard_core/web/ \| grep -vi "router"` (expect no auth deps) |
| Four routers / prefixes unchanged | `grep -n "include_router" shard_core/app_factory.py; grep -n "prefix" shard_core/web/*/__init__.py` |
| forwardAuth targets unchanged | `grep -n "address=" shard_core/service/traefik_dynamic_config.py` |
| shard_core still publishes no ports; stop_grace_period | `grep -n -A3 "shard_core:" docker-compose.yml \| grep -n "ports\|stop_grace"` |
| JWT still has no exp claim | `grep -n -A6 "def create_terminal_jwt" shard_core/service/pairing.py` |
| Crypto still RSA-4096 / RSA_PSS_SHA512 | `grep -rn "generate_private_key\|RSA_PSS" shard_core/service/{crypto,signed_call,peer}.py` |
| Status allow-lists / exclusion filters | `grep -n "app_status in\|status !=\|status not in" shard_core/service/app_tools.py shard_core/service/app_lifecycle.py shard_core/service/app_installation/util.py` |
| on_apps_update receivers (websocket + cache invalidation) | `grep -rn "on_apps_update.connect" shard_core/` |
| Startup order in lifespan | `sed -n '78,108p' shard_core/app_factory.py` |
| throttle still global, still 5s | `grep -n -B1 "def docker_start_app" shard_core/service/app_tools.py; sed -n '1,30p' shard_core/util/misc.py` |
| peer.py httpx/requests mismatch still present (or fixed) | `grep -n "httpx.HTTPStatusError" shard_core/service/peer.py` |
| Backup dirs still exclude postgres_data; issue #122 state | `grep -n -A2 "services.backup" config.toml; gh issue view 122 --json state` |
| Backup event-loop blockers still present | `grep -n "subprocess.run\|upload_blob\|command.split" shard_core/service/backup.py` |
| Migrations still CWD-relative | `grep -n "Path.cwd" shard_core/database/migration.py shard_core/app_factory.py` |
| initial_apps / registries in config | `grep -n "initial_apps\|registries" config.toml` |
