---
name: freeshard-domain-reference
description: Theory pack for shard_core's protocols and standards AS APPLIED HERE — HTTP Message Signatures (RSA-PSS, not Ed25519), shard ID / short_id derivation, Traefik forwardAuth + errors middleware + DNS-01 wildcard ACME, terminal JWT pairing, rclone crypt backups, compose-file-per-app orchestration, yoyo + psycopg3 transaction semantics, Pydantic v2 idioms. TRIGGER on "how does peer/signature auth work", "key_id / short_id / shard id", edits to shard_core/service/{crypto,signed_call,peer,pairing,backup,traefik_dynamic_config}.py, data/traefik.yml, migrations/, shard_core/settings.py, app_meta versioning, X-Forwarded-* / X-Ptl-* headers, "forwardAuth protocol mechanics" (for "why is there no auth on this route", use freeshard-architecture-contract), rclone flags, "where do transactions commit". SKIP when you need step-by-step failure triage (use freeshard-debugging-playbook), running/deploying the stack (freeshard-run-and-operate), config-key catalogs (freeshard-config-and-flags), cross-repo type sync (freeshard-ecosystem-contracts), or writing tests (freeshard-testing-and-qa).
---

# Freeshard Domain Reference

The theory a zero-context engineer needs before touching shard_core's crypto, proxy, auth, backup, orchestration, DB, or settings code. Each section: what you must know, how THIS repo uses it (file:line), and the classic mistake. Line numbers verified 2026-07-03 against origin/main (v0.39.4); the branch you're on may drift — re-grep before relying on an exact line.

**Terms used throughout** (defined once):

| Term | Meaning |
|---|---|
| shard | One user's personal cloud VM running the shard_core stack (this repo) |
| shard_core | The FastAPI control-plane app in this repo, container port 80 |
| controller | freeshard-controller — central cloud management service at controller.freeshard.net (separate repo) |
| terminal | A paired end-user device/browser (holds a JWT cookie) |
| peer | Another shard, authenticated by HTTP message signature |
| identity | An RSA keypair + derived ID; the default identity IS the shard's identity |
| `portal` | Legacy project name (pre-2025 rename). Survives as the docker network name, jinja2 template var, `X-Ptl-*` header prefix, `portal_controller.py`. Never "fix" this naming in passing. |
| kv_store | Postgres table of JSON values keyed by string; shard_core's junk drawer for secrets/flags |

---

## 1. HTTP Message Signatures (IETF RFC 9421 family)

**What you must know.** Requests between shards, and from shard to controller, are authenticated by signing HTTP request components (method, URL, headers, body digest) with the sender's private key. The `requests-http-signature` library (over `http_message_signatures`) does the signing/verification; the verifier looks up the public key by the `keyid` parameter embedded in the `Signature-Input` header. Because the signature covers the URL, **the verifier must reconstruct the exact URL the sender signed** — behind a reverse proxy that means rebuilding it from forwarded headers.

**How this repo uses it.**
- Outgoing (shard → controller, shard → peer): `shard_core/service/signed_call.py:14-30` — `signed_request(...)` wraps `requests.request` in `asyncio.to_thread` with `HTTPSignatureAuth(signature_algorithm=algorithms.RSA_PSS_SHA512, key_id=identity.short_id, key=<private key PEM>)`. The `key_id` is the shard's 6-char `short_id` (section 2).
- Incoming (peer → this shard): `shard_core/service/peer.py:79-106` `verify_peer_auth`. Traefik's forwardAuth sub-request doesn't carry the original request line, so the code rebuilds a `requests.Request` from the headers `X-Forwarded-Method`, `X-Forwarded-Proto`, `X-Forwarded-Host`, `X-Forwarded-Uri` plus the body, then calls `HTTPSignatureAuth.verify(..., algorithms.RSA_PSS_SHA512, key_resolver=_PreloadedKR(...))`. The key resolver is sync, so all peers are preloaded from the DB into a dict keyed by `peer.short_id` first (`peer.py:85-92`, resolver at `peer.py:109-122`). The verified `keyid` then resolves the peer row by ID prefix.
- Incoming (shard → controller side): `freeshard-controller` repo, `freeshard-controller-backend/freeshard_controller/api/auth.py` — `_verify_request` rewrites the scheme from `x-forwarded-proto` before verifying with the same `RSA_PSS_SHA512`, and caches shard public keys in a module dict because the key resolver can't be async.
- Peers learn each other's public keys by fetching `GET /core/public/meta/whoareyou` (returns `OutputIdentity` incl. `public_key_pem`; `shard_core/web/public/meta.py:21`), triggered on peer insert via the `async_on_peer_write` signal (`peer.py:125-127`).

**Classic mistakes.**
- Touching the proxy header config. The `X-Forwarded-*` headers are **load-bearing crypto inputs**: if Traefik (or any middleware) stops forwarding them, or rewrites host/URI, every peer signature verification fails. Same on the controller side with `x-forwarded-proto`.
- Dropping semantically load-bearing headers in a sign-and-forward proxy. shard_core's `/internal/call_backend` proxy once forwarded a body without its `Content-Type`; years later a FastAPI upgrade on the controller (strict content-type parsing) turned every proxied write into a 422 while reads stayed green. When proxying, forward `Content-Type` with the body.
- Making the key resolver async or lazy — the library calls it synchronously; that's why both sides preload/caches keys.

## 2. RSA-PSS keys and shard IDs (the Ed25519 myth)

**What you must know.** `agents.md` claims Ed25519 crypto. **This is false — do not implement against it.** The code is RSA-4096 end to end. Verify yourself: `grep -ri ed25519 shard_core/` → zero hits.

**How this repo uses it.**
- Key generation: `shard_core/service/crypto.py:52-57` — `rsa.generate_private_key(public_exponent=65537, key_size=4096)`.
- Raw sign/verify (not HTTP): PSS padding, MGF1(SHA-256), SHA-256 digest (`crypto.py:34-46, 79-86`).
- HTTP message signatures: `algorithms.RSA_PSS_SHA512` (`signed_call.py:27`, `peer.py:103`). Two different digest choices in one codebase — both RSA-PSS, neither Ed25519.
- Shard ID pipeline: public key PEM bytes → SHA-512 → `human_encoding.encode` (`crypto.py:29-32`). The encoding (`shard_core/service/human_encoding.py`) maps 5 bits per character onto a 32-char alphabet `abcdefghjklnpqrstvwxyz0123456789` (line 102 — note: no `i`, `m`, `o`, `u`; chosen to avoid lookalikes). 512 bits / 5 = **103-character ID** (verified by generating a key).
- `short_id` = first 6 chars of the ID (`shard_core/data_model/identity.py:44-47`); the shard's domain = `id[:dns.prefix_length].lower() + "." + dns.zone` with `prefix_length` defaulting to 6 (`identity.py:58-64`, `shard_core/settings.py:10-12`). So a hosted shard lives at e.g. `c0p3x5.freeshard.cloud`.
- 6 chars × 5 bits = 30 bits of prefix. That is a deliberate usability/security compromise: the short_id is a routable DNS label and a signature `keyid`, not a security boundary by itself — trust comes from the full-ID/public-key binding (peers verify `peer_identity.id.startswith(peer.id)` on refresh, `peer.py:60-63`, and the `Peer` model validates pubkey-matches-id). Collision handling between hosted shards' short_ids would have to live controller-side — **not verifiable from this repo (unverified as of 2026-07-03)**.

**Classic mistake.** Writing new signing/verification code against Ed25519 because agents.md says so, or "harmonizing" the SHA-256 raw-crypto and SHA-512 HTTP-signature digests. Both changes break every existing identity and peer relationship — key format and ID derivation are wire/storage contracts.

## 3. Traefik mechanics (forwardAuth is THE auth layer; repo compose pins v3.6, fleet runs v2.11 — see below)

**What you must know.** FastAPI enforces **no** auth. There is no `Depends` auth anywhere in `shard_core/web/`. All authentication happens in Traefik via `forwardAuth` middlewares: Traefik sends a sub-request to a shard_core `/internal/*` endpoint; 2xx = allow, and selected response headers are copied onto the upstream request. `/internal/*` itself is protected only by network topology (shard_core publishes no host ports; only Traefik does — `docker-compose.yml:32-35`; everything shares the docker network `portal`).

**How this repo uses it.** Dynamic config is compiled in Python (`shard_core/service/traefik_dynamic_config.py`) and written to `{path_root}/core/traefik_dyn/traefik_dyn.yml`; static config is rendered from `data/traefik.yml` at `create_app()` time. The routing map and auth-level table (external routes → middlewares → auth targets, incl. the dashboard) is owned by **freeshard-architecture-contract §1** — this section carries only the protocol theory behind it.

- `strip` removes the `/core/` prefix (`stripPrefix.prefixes=["/core/"]`, :82-85): external `/core/protected/apps` hits FastAPI at `/protected/apps`. Router prefixes and Traefik rules must stay in lockstep.
- **errors middleware discards upstream bodies.** `app-error` catches status `400-499`/`500-599` from app containers and replaces the ENTIRE response with the splash page from `GET /internal/app_error/{status}` (`shard_core/web/internal/app_error.py:26-32`). A FastAPI 422 detail from an app is gone; only the status survives. Known pain: https://github.com/FreeshardBase/freeshard/issues/91 (open as of 2026-07-03: embed the real upstream response hidden in the splash).
- **Wildcard cert ⇒ DNS-01 ⇒ hardcoded provider.** Every app gets `<app>.<domain>`, so certs are issued for `<domain>` + `*.<domain>` (`traefik_dynamic_config.py:215-221`). Let's Encrypt only issues wildcards via the DNS-01 challenge, and the challenge provider is hardcoded `provider: azure` in `data/traefik.yml` (with the Azure credential env vars stubbed in `docker-compose.yml:38-42`). Non-Azure DNS = no certs until both are changed. That Traefik-on-every-shard holds DNS-zone credentials is acknowledged security debt with a TSIG-based redesign under discussion — treat as open, don't build on it.
- **readTimeout is load-bearing.** `data/traefik.yml` (origin/main) sets `respondingTimeouts.readTimeout: "300s"` on the http and https entrypoints; `writeTimeout` deliberately stays 0 so downloads/SSE aren't cut. History: with readTimeout=0, internet scanners hold half-open connections forever; each holds a file descriptor; traefik eventually EMFILEs and the shard goes dark while the container still shows "Up" (PR https://github.com/FreeshardBase/freeshard/pull/108). Related Go lore: binaries built with Go < 1.19 do **not** self-raise `RLIMIT_NOFILE` to the hard limit (Go 1.19 added that), so an old traefik build in a container with soft nofile 1024 dies far earlier than a new one. Diagnostic: `docker exec traefik sh -c 'ulimit -n'`.
- This repo pins `traefik:v3.6` (`docker-compose.yml:29`, as of 2026-07-03). Deployed-fleet traefik versions are controller territory — don't assume they match.

**Classic mistakes.**
- Adding a "protected" FastAPI route and assuming something in-process checks auth. Nothing does. Any container on the `portal` network can `curl http://shard_core/protected/...` or `/management/...` directly — the mock app template in tests joins that same external network (`tests/mock_app_store/mock_app/docker-compose.yml.template`). Endpoints trusting `X-Ptl-*` request headers (e.g. `GET /protected/backup/passphrase` reads `X-Ptl-Client-Id`) are only trustworthy through Traefik.
- Regenerating the 1117-line `shard_core/data_model/traefik_dyn_config.py` model. It was hand-patched to add `authResponseHeadersRegex`; the generator script deliberately raises on import (`scripts/generate_traefik_dyn_config_model.py:6`). Regenerating silently drops the field the app-auth middleware depends on.
- Adding a per-request DB query to `/internal/auth`. It runs on EVERY app request; it's zero-DB at steady state via module-global `_identity_cache`/`_app_cache` invalidated by blinker signals (`shard_core/web/internal/auth.py:32-44`). A 4-conn pool once exhausted under a ~30-request SPA burst → batch 500s (issue https://github.com/FreeshardBase/freeshard/issues/89, PR #90). New lookups on this path need a cache + signal invalidation.

## 4. Terminal pairing and JWTs

**What you must know.** Terminal sessions are HS256 (shared-secret) JWTs — symmetric, unlike the RSA peer scheme. Freeshard treats *pairing* as the auth boundary: a paired device gets long-lived access; revocation is by deleting the terminal, not by token expiry.

**How this repo uses it** (`shard_core/service/pairing.py`):
- Secret: auto-generated on first use, `secrets.token_urlsafe(settings().terminal.jwt_secret_length=64)`, stored in kv_store key `terminal_jwt_secret` (:92-98).
- Payload: `{sub: terminal_id, iat}` — **deliberately no `exp`** (:59-66). `verify_terminal_jwt` decodes, then looks up the terminal row by `sub`; a deleted terminal ⇒ `InvalidJwt` (:69-89). Row existence IS the revocation mechanism. An optional `Bearer ` prefix is stripped (:75-77).
- Pairing code: 6 random digits, **single active code** stored in kv_store key `pairing_code` (a new one overwrites the old), default validity `terminal.pairing_code_deadline=600s` (`settings.py:104-106`), deleted on redemption (:28-56). Minted via `GET /protected/terminals/pairing-code`, `GET /management/pairing_code` (controller-initiated), or printed in the first-start welcome log.
- Redemption (`shard_core/web/public/pair.py`): inserts the terminal and sets cookie `authorization`, `domain=<shard domain>`, `secure`, `httponly`, `expires=60*60*24*356*10` (~10 years; the 356 is a long-standing typo for 365 — harmless, don't be confused by it).

**Classic mistakes.**
- "Fixing" the missing `exp`. Adding expiry breaks the product model (paired ≈ permanent) and buys nothing: revocation already works via row deletion, and every verification hits the terminals table anyway.
- Assuming a second pairing code can coexist — minting a code invalidates the previous one (single kv slot). UI/flows that fetch a code twice race themselves.

## 5. rclone crypt backups to Azure Blob

**What you must know.** `rclone` "connection-string" remotes need no config file: `:azureblob:<container>` is an on-the-fly Azure Blob remote (authenticated here by `--azureblob-sas-url`), and `:crypt:<path>` wraps another remote (`--crypt-remote`) with client-side encryption. `rclone sync` makes the destination match the source (deletes remote extras). `rclone obscure` is reversible obfuscation of the password for the command line — it is NOT encryption; the crypt passphrase itself does the encrypting. `--fast-list` trades memory for drastically fewer List calls — on Azure, per-directory List ops are billed and can cost multiples of the storage itself.

**How this repo uses it** (`shard_core/service/backup.py`, origin/main):
- Trigger: CronTask `0 3 * * *` + uniform random jitter ≤3600s (`config.toml [services.backup.timing]`), or `POST /protected/backup/start`.
- SAS URL comes from the controller: signed `GET api/shard_backup/backup_sas_url` (`shard_core/service/portal_controller.py:39-42`). Self-hosted shards (no controller) therefore cannot run this backup path.
- Command (`COMMAND_TEMPLATE`, backup.py top): `rclone --azureblob-sas-url <SAS> --crypt-password <obscured> --crypt-remote :azureblob:{container} sync {dir} :crypt:{container}/{dir} --create-empty-src-dirs --stats-log-level NOTICE --stats 1000m --use-json-log --fast-list` for each of `directories = ["core", "user_data"]`, cwd = `path_root`. Passphrase: plaintext in kv_store key `backup_passphrase` (10 EFF-wordlist words, auto-generated at startup), obscured via a sync `subprocess.run(["rclone","obscure",...])`.
- Flag history you must respect: `--fast-list` and `--azureblob-no-check-container` were both added for Azure cost (PR #106); `--azureblob-no-check-container` was then **removed** because the image bundles rclone 1.60.1 from Debian bookworm apt (`Dockerfile:30`) and that flag needs ≥1.61.0 — every backup died with `unknown flag` (issue https://github.com/FreeshardBase/freeshard/issues/117, PR #119). A regression test pins this: `tests/test_backup.py::test_command_templates_only_use_supported_flags`.
- Stats protocol: with `--use-json-log` rclone writes JSON log lines to **stderr**; the code takes the last line (`stderr.split("\n")[-2]`), parses it, and stores `rclone_result["stats"]` in the report. `BackupStats.rclone_stats` is typed `dict` on purpose (`shard_core/data_model/backup.py:11`): rclone's stats schema shifts between versions, and modeling it once caused validation failures (commit b9dfcfd "treat rclone stats as opaque dict"). Since PR #119 the process returncode is checked first and non-zero raises `BackupFailedError` with stderr.
- After a successful run, a `_last_backup` marker blob is uploaded; its Last-Modified is the controller's recency signal (failures only warn).

**Classic mistakes.**
- Giving `rclone_stats` a typed schema. Keep it an opaque dict.
- Adding any rclone flag without checking it exists in 1.60.1 (`docker run --rm python:3.13-slim-bookworm sh -c 'apt-get update -qq && apt-cache policy rclone'`).
- Assuming the backup covers the database. It syncs only `core/` and `user_data/`; **Postgres data (`postgres_data/`, containing identities/private keys, terminals, kv_store) is NOT in the rclone backup set** — whether hosted infra snapshots it separately is outside this repo.
- The command is built with `str.split()` on the template — any whitespace in the SAS URL or paths breaks tokenization. Know it before you extend the template.

## 6. Docker Compose orchestration of apps

**What you must know.** shard_core is a compose-driving control plane: every installed app is its own compose project, started/stopped by shelling out to `docker compose` against the **host's** docker daemon through the mounted `/var/run/docker.sock` (`docker-compose.yml:60`). Because the daemon is the host's, volume paths inside app compose files must be host paths, not container paths.

**How this repo uses it.**
- Template: each app ships `docker-compose.yml.template`, rendered with jinja2 (`shard_core/service/app_installation/util.py:78-100`) with two var groups: `fs.{app_data, all_app_data, shared, installation_dir}` — all under `settings().path_root_host` (host side!) — and `portal` = the shard's `SafeIdentity` (`domain`, `id`, `short_id`, `public_key_pem`). ALL templates are re-rendered at every startup (`util.py:65-75`), so templates must be idempotent. App containers join the external network `portal` — same network as shard_core (see §3 classic mistake).
- Path invariant: `path_root` (in-container view, `/` in prod, `run/` in dev) for everything shard_core itself reads/writes; `path_root_host` ONLY for paths rendered into app compose files.
- Lifecycle (idle-stop): every authorized app request fires `on_request_to_app` (`web/internal/auth.py:111`), which records `time.time()` in an **in-memory** dict and fire-and-forgets a start (`shard_core/service/app_lifecycle.py:24-36`). A `PeriodicTask control_apps` (every 10s in prod, `config.toml [apps.lifecycle]`) stops non-`always_on` apps idle longer than `lifecycle.idle_time_for_shutdown` (default 60s, min 5, mutually exclusive with `always_on` — validators at `shard_core/data_model/app_meta.py:90-111`), starts `always_on` apps, and stops everything when disk space is low. The in-memory dict is lost on restart, so all running non-always-on apps get stopped on the first tick after boot; the DB `last_access` column is a separate, slower signal not consulted by idle-stop.
- The docker.sock control plane is acknowledged security debt: a compromised shard_core (or anything that reaches the socket) owns the host. Don't widen the surface.
- **Healthcheck/depends_on gating — the PWA lie.** Idle-stopped apps cold-start on first request; the splash (§3) shows until the app responds non-error. A split web/backend app whose web container 200s before the backend is ready makes the proxy think "up" and skips the splash into a broken UI; worse, an installed PWA's service worker serves its cached shell *without hitting the proxy at all*. Mitigation pattern for app authors: gate the entrypoint container with `depends_on: condition: service_healthy` on the backend. Related open work: startup/migration visibility https://github.com/FreeshardBase/freeshard/issues/120 and a no-interruption window during updates https://github.com/FreeshardBase/freeshard/issues/121 (both open as of 2026-07-03).

**Classic mistakes.**
- Using `path_root` in a compose template (container path handed to the host daemon → empty/wrong mounts).
- Trusting "container Up" or an early 200 as app-ready — health is per-entrypoint semantics, not container state.
- Forgetting `await signals.on_apps_update.send_async()` after a status change: it drives both the websocket UI push and the `/internal/auth` app-cache invalidation; forgetting it serves stale auth decisions.

## 7. yoyo-migrations + psycopg3 async pool

**What you must know.** yoyo applies plain-SQL migration files at startup (sync, before the app serves). psycopg3's pool hands out connections as async context managers: **exiting the `connection()` block commits; an exception inside rolls back**. One `async with` block = one transaction. You never call `conn.commit()`.

**How this repo uses it.**
- Startup: `database.init_database()` (`shard_core/database/database.py:26-34`) = sync `migrate()` → open pool → one-time TinyDB→Postgres data import. Called first thing in lifespan.
- `migrate()` (`shard_core/database/migration.py`): `get_backend("postgresql+psycopg://...")`, reads `Path.cwd() / "migrations"`, applies under `backend.lock()`. CWD-dependent: run from repo/image root or it silently finds zero migrations.
- Exactly one migration exists as of 2026-07-03: `migrations/shard-core-0001-init.sql`, header `-- shard-core-0001-init` / `-- depends:` (yoyo's ID + dependency lines), all `CREATE TABLE IF NOT EXISTS` (idempotent against pre-yoyo databases). New migrations: `shard-core-NNNN-<slug>.sql` with `-- depends: <previous-id>` (naming convention implied by the single existing file, not documented elsewhere).
- Pool: module-global `AsyncConnectionPool`, `max_size=20, timeout=10` (`shard_core/database/connection.py:17-33`) — the 20 is a fix for forwardAuth pool exhaustion (issue #89); don't shrink it. `db_conn()` (:52-55) is the only sanctioned way to get a connection.
- Access pattern: every function in `shard_core/database/*.py` takes `conn: AsyncConnection` as first arg; callers do `async with db_conn() as conn:`. `grep -rn "commit()" shard_core/` → zero hits, by design. `database.py` additionally offers pool-managing `get_value/set_value/remove_value` for one-shot kv_store ops.

**Classic mistakes.**
- Calling `conn.commit()` or wrapping extra transaction management — the context manager already does it; explicit commits mask the rollback-on-exception guarantee.
- Spreading one logical write across two `db_conn()` blocks and assuming atomicity — each block is its own transaction.
- Holding a `db_conn()` block open across slow awaits (HTTP calls, subprocesses): with `max_size=20` and forwardAuth traffic, hoarded connections recreate issue #89.

## 8. Pydantic v2 idioms used here

**What you must know.** Three v2 features carry real weight in this repo: layered `BaseSettings` sources, `@computed_field` (which puts derived properties INTO serialized output), and `model_validator(mode="before")` as a data-migration hook that rewrites raw input before validation.

**How this repo uses it.**
- Settings layering (`shard_core/settings.py:109-152`): `settings_customise_sources` builds one `TomlConfigSettingsSource` **per file** so overlay files override individual fields, not whole nested sections. Precedence: init kwargs > env (`FREESHARD_` prefix, `__` nested delimiter, e.g. `FREESHARD_TRAEFIK__DISABLE_SSL`) > `local_config.toml` (if present) > `config.toml`. Access is via the `settings()` singleton (:155-159). A `CONFIG` env var appears in the justfile/CI but is read by nothing — dead.
- `@computed_field` on `Identity`/`SafeIdentity` (`shard_core/data_model/identity.py:44-64`): `short_id`, `public_key_pem`, `domain` are computed AND serialized — that's why `GET /public/meta/whoareyou` returns them and why compose templates can use `{{ portal.short_id }}`. `domain` reads `settings()` at property-access time, so identity serialization depends on live settings.
- AppMeta version-migration chain (`shard_core/data_model/app_meta.py:128-140` + `app_meta_migration.py`): `CURRENT_VERSION = "1.2"`. A `model_validator(mode="before")` loops: while `values["v"] != CURRENT_VERSION`, look up `migrations[values["v"]]` (dict keyed by OLD version) and apply. Each migration function must set `values["v"]` to the next version or the loop raises "migration seems to be stuck". This lets years-old app-store zips (`app_meta.json` v1.0) parse today. To bump the format: add `migrate_1_2_to_1_3` to the dict under key `"1.2"`, set `CURRENT_VERSION = "1.3"`.
- `shard_core/data_model/backend/` is a verbatim copy of controller models (`just get-types`), every file stamped `# DO NOT MODIFY`. `Profile.from_shard` uses `getattr(shard, field, default)` for newer fields (`shard_core/data_model/profile.py:42-46`) so a stale copy degrades gracefully instead of stripping fields — a real shipped failure (fields silently dropped at re-validation; fixed in commits 6d4b101 + e55ce51). Cross-repo procedure: freeshard-ecosystem-contracts.

**Classic mistakes.**
- Editing files under `data_model/backend/` — the next `just get-types` erases your change.
- Adding a migration function that forgets to bump `values["v"]` → infinite-loop guard exception for every app parse.
- Assuming `model_validate` keeps unknown fields. It strips them — that's exactly how the profile/billing fields vanished. When data passes THROUGH shard_core to another consumer, either type it fully (after a type sync) or pass it opaquely.

---

## When NOT to use this skill

| You actually want | Go to |
|---|---|
| Symptom→cause triage, discriminating experiments | freeshard-debugging-playbook |
| History of incidents/reverts with evidence | freeshard-failure-archaeology |
| Which invariants must hold and why (decision records) | freeshard-architecture-contract |
| Every config key, env override rules, dead config | freeshard-config-and-flags |
| Dev env setup, uv, worktrees | freeshard-build-and-env |
| Running the stack, first start, release, restore | freeshard-run-and-operate |
| Test fixtures, adding tests, flaky tests | freeshard-testing-and-qa |
| Controller/web-terminal/app-repository contracts, `just get-types` | freeshard-ecosystem-contracts |
| Change gates, review rules, release discipline | freeshard-change-control |
| OIDC identity provider campaign | freeshard-oidc-identity-campaign |

## Provenance and maintenance

Written 2026-07-03 against origin/main (`0a40684`, v0.39.4) with cross-checks into the freeshard-controller sibling checkout. Primary sources: repo code as cited per section; GitHub issues/PRs https://github.com/FreeshardBase/freeshard/issues/89, /pull/90, /issues/91, /pull/106, /pull/108, /issues/117, /pull/119, /issues/120, /issues/121; commits b9dfcfd, 6d4b101, e55ce51, fd1d05b.

Drift-prone facts — re-verify before relying:

| Fact (as of 2026-07-03) | Re-verify with |
|---|---|
| Signing is RSA-4096 / RSA_PSS_SHA512, not Ed25519 | `grep -rn "RSA_PSS_SHA512\|generate_private_key" shard_core/service/{signed_call,crypto,peer}.py` |
| Shard ID = 103 chars, alphabet in human_encoding.py:102 | `grep -n 'init("' shard_core/service/human_encoding.py` |
| Traefik pinned v3.6; images 0.39.4 / web-terminal 0.37.4 | `git fetch && git show origin/main:docker-compose.yml \| grep image:` |
| readTimeout 300s on http/https entrypoints | `git show origin/main:data/traefik.yml \| grep -A2 respondingTimeouts` |
| DNS-01 provider hardcoded `azure` | `grep -n "provider:" data/traefik.yml` |
| errors-middleware splash swallows bodies; #91 still open | `gh issue view 91 --json state` |
| rclone flags: `--fast-list` yes, `--azureblob-no-check-container` absent; rclone from bookworm apt | `git show origin/main:shard_core/service/backup.py \| sed -n '/COMMAND_TEMPLATE/,/^"""/p'` and `grep -n rclone Dockerfile` |
| JWT payload has no `exp`; HS256; kv key `terminal_jwt_secret` | `grep -n "sub\|iat\|HS256" shard_core/service/pairing.py` |
| One yoyo migration; naming `shard-core-NNNN-*` | `git ls-tree origin/main migrations/` |
| Pool max_size=20, timeout=10 | `grep -n "max_size\|timeout" shard_core/database/connection.py` |
| AppMeta CURRENT_VERSION "1.2" | `grep -n CURRENT_VERSION shard_core/data_model/app_meta.py` |
| agents.md still claims Ed25519 (stale-doc warning still needed) | `grep -in ed25519 agents.md` |
| Settings precedence env > local_config.toml > config.toml | read `settings_customise_sources` in shard_core/settings.py |
