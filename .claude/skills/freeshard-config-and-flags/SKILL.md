---
name: freeshard-config-and-flags
description: "Catalog of every shard_core configuration axis and how overrides actually work. Use when adding/changing/reading a config option, wiring a FREESHARD_* env var, editing config.toml / local_config.toml / tests/config.toml / .env.template / docker-compose.yml environment mappings, checking whether a feature flag exists, or debugging 'my override does nothing' / 'Settings() crashes at boot'. TRIGGER on shard_core/settings.py, pydantic-settings, env_nested_delimiter, FREESHARD_ env vars, DISABLE_SSL, telemetry.enabled, apps.pruning, settings_override, config_override. SKIP when the question is about running/deploying the stack (use freeshard-run-and-operate), test fixture design beyond config overrides (use freeshard-testing-and-qa), or why a config decision was made (use freeshard-architecture-contract)."
---

# Freeshard config and flags

**shard_core** is the FastAPI backend of a Freeshard shard (a personal cloud VM). All of its
configuration flows through one pydantic-settings class: `Settings` in
`shard_core/settings.py:109`. This skill is the complete catalog of every option, the override
rules, the dead config you must not trust, and the checklist for adding an option.

Command outputs verified against the repo on 2026-07-03, and re-verified for the config surface
on 2026-07-15 (issue #128). Line numbers in file:line references drift with every commit and are
not re-checked on each update — treat them as a starting point and grep for the symbol.

## Precedence chain and file map

Highest priority first (`settings_customise_sources`, `shard_core/settings.py:129-152`):

| Priority | Source | When active | Notes |
|---|---|---|---|
| 1 | `Settings(...)` init kwargs | tests only (`tests/conftest.py:147-150`) | |
| 2 | Env vars `FREESHARD_*` | always | see override rules below |
| 3 | `local_config.toml` | only if the file exists in CWD | dev overlay; excluded from the Docker image via `.dockerignore` (commit 773f736) |
| 4 | `config.toml` | always | prod baseline, baked into the image (`Dockerfile:21` `ADD . .`) |

Key semantics:

- **Per-field overlay**: each TOML file gets its own `TomlConfigSettingsSource`, so an override
  file replaces individual fields, not whole nested sections. `local_config.toml` setting only
  `[dns] zone` keeps `dns.prefix_length` from `config.toml`.
- **CWD-relative paths**: the file names are literal strings `"config.toml"` /
  `"local_config.toml"` (`settings.py:143,150`). Start shard_core from the repo root (Docker
  WORKDIR is `/app`). Started elsewhere, ALL TOML config is silently lost and you get
  required-field `ValidationError`s.
- **Lazy singleton**: code reads config via `settings()` (`settings.py:155-159`); tests swap it
  with `set_settings()` / `reset_settings()`. Never instantiate `Settings()` in product code.
- Tests replace the `local_config.toml` overlay with `tests/config.toml` via a `_TestSettings`
  subclass (`tests/conftest.py:54-59`) — see "How tests override config" below.

## Env-var override rules

- Prefix `FREESHARD_`, nested delimiter `__` (double underscore) — `settings.py:110-113`.
- Correct forms: `FREESHARD_DNS__ZONE`, `FREESHARD_TRAEFIK__ACME_EMAIL`,
  `FREESHARD_TRAEFIK__DISABLE_SSL`, `FREESHARD_FREESHARD_CONTROLLER__BASE_URL`,
  `FREESHARD_DB__HOST`. Top-level scalars take a single level: `FREESHARD_PATH_ROOT`,
  `FREESHARD_PATH_ROOT_HOST`.

### Trap: single-underscore nesting is SILENTLY ignored

pydantic-settings raises no error for `FREESHARD_DNS_ZONE` — it just doesn't match, and the
value falls back to the TOML files. This caused a production incident: commit 5de2998
(2026-04-13) fixed `docker-compose.yml`, where single-underscore names made every self-hosted
shard silently fall back to the hardcoded zone `freeshard.cloud` and hardcoded ACME email.

The same bug class hit the justfile recipe `run-dev-for-freeshard-controller`, which set
`FREESHARD_FREESHARD_CONTROLLER_BASE_URL` — one underscore short before `BASE_URL` — and so
silently talked to the **production** controller. Fixed 2026-07-15 (issue #128); the recipe now
uses `FREESHARD_FREESHARD_CONTROLLER__BASE_URL`. Both incidents were name-shape bugs that no
error message reported, which is why the verify-one-liner below is not optional.

### Verify-an-override one-liner

Whenever you add or touch a `FREESHARD_*` var (compose, justfile, CI), prove it lands. From
repo root:

```bash
FREESHARD_DNS__ZONE=probe.test .venv/bin/python -c \
  "from shard_core.settings import Settings; print(Settings().dns.zone)"
# must print: probe.test
```

Substitute your section/field. If it prints the TOML value instead, the var name is wrong.

## Full option catalog

Legend: **prod** = `config.toml` (baked into image), **dev** = `local_config.toml`,
**test** = `tests/config.toml`. Blank cell = not set there (default/prod value applies).
Model definitions all in `shard_core/settings.py`.

### Top level

| Option | Type | Default | Prod | Dev | Consumer | Notes |
|---|---|---|---|---|---|---|
| `path_root` | str | `/` | `/` | `run/` | `service/disk.py:24`, `service/backup.py:51`, `service/assets.py:8`, `app_installation/util.py`, `database/tinydb_migration.py`, `app_factory.py` | Container-internal root for `core/` and `user_data/`. Tests set it per-test to `tmp_path` (`tests/conftest.py:148`). |
| `path_root_host` | str | `/home/shard` | `/home/shard` | | `app_installation/util.py:80-85` | HOST-side path, used ONLY to render volume mounts into app docker-compose templates (host docker daemon resolves them). Prod compose overrides via `FREESHARD_PATH_ROOT_HOST=${FREESHARD_DIR:?}` (`docker-compose.yml:67`). |

### [db] — DatabaseSettings (settings.py:92-97)

| Option | Type | Default | Prod | Consumer |
|---|---|---|---|---|
| `host` | str | `postgres` | `postgres` | `database/connection.py:19` (async pool conninfo), `database/migration.py:13` (yoyo) |
| `port` | int | `5432` | `5432` | same |
| `dbname` / `user` / `password` | str | `shard_core` each | same | same — matches hardcoded `POSTGRES_*` env on the postgres compose service (`docker-compose.yml:14-17`) |

Tests inject a different DB (`shard_core_test` on host port from pytest-docker) as an init
kwarg (`tests/conftest.py:149`).

### [dns] — DnsSettings (settings.py:10-12)

| Option | Type | Default | Prod | Dev | Consumer |
|---|---|---|---|---|---|
| `zone` | str | REQUIRED | `freeshard.cloud` | `localhost` | `data_model/identity.py:63` — shard domain = `identity.id[:prefix_length].lower() + "." + zone`. Self-hosted: `FREESHARD_DNS__ZONE=${DNS_ZONE:?}` (`docker-compose.yml:64`). |
| `prefix_length` | int | `6` | `6` | | `data_model/identity.py:62` |

### [services.backup] — BackupSettings (settings.py:15-23)

| Option | Type | Default | Prod | Consumer |
|---|---|---|---|---|
| `directories` | list[str] | REQUIRED | `["core", "user_data"]` | `service/backup.py:52` — the rclone-crypt sync set. Note: Postgres data is NOT in it. |
| `timing.base_schedule` | cron str | REQUIRED | `0 3 * * *` | `app_factory.py:131` (CronTask start_backup) |
| `timing.max_random_delay` | int (s) | REQUIRED | `3600` | `app_factory.py:132`, jitter applied `util/async_util.py:93-94` |

### [traefik] — TraefikSettings (settings.py:30-32)

| Option | Type | Default | Prod | Consumer |
|---|---|---|---|---|
| `acme_email` | str | REQUIRED | `contact@freeshard.net` | rendered into Traefik static config (`app_factory.py:140-157`). Self-hosted: `FREESHARD_TRAEFIK__ACME_EMAIL=${EMAIL:?}`. |
| `disable_ssl` | bool | `False` | | feature flag — see Feature-flag inventory |

### [apps] — AppsSettings (settings.py:65-72)

| Option | Type | Default | Prod | Test | Consumer |
|---|---|---|---|---|---|
| `app_store.base_url` | str | REQUIRED | `https://storageaccountportab0da.blob.core.windows.net` | | `app_installation/worker.py:181-182`, `app_installation/util.py:58-59` — app-zip download URLs |
| `app_store.container_name` | str | REQUIRED | `app-store` | | same |
| `registries` | list[{uri,username,password}] | `[]` | one entry: `portalapps.azurecr.io` + **plaintext credentials** | | `app_installation/__init__.py:123-133` — `docker login` at startup. See "Committed registry credentials". |
| `lifecycle.refresh_interval` | int (s) | `30` | `10` | `2` | `app_factory.py:115` — period of `control_apps` |
| `initial_apps` | list[str] | `[]` | `["filebrowser", "immich", "paperless-ngx"]` | | `app_installation/__init__.py:110` — first-start install queue, guarded by kv flag `initial_apps_installed` |
| `last_access.max_update_frequency` | int (s) | `60` | `60` | `3` | `data_model/app_meta.py:158-161` — debounce on app last-access writes |
| `usage_reporting.tracking_schedule` | cron | REQUIRED | `0 2 * * *` | `* * * * * *` | `app_factory.py:117-120` |
| `usage_reporting.reporting_schedule` | cron | REQUIRED | `0 3 1 * *` | `* * * * * */3` | `app_factory.py:121-124`; posts to `{management.api_url}/app_usage` (`service/app_usage_reporting.py:54-55`) |
| `pruning.schedule` | cron | REQUIRED | `0 4 * * *` | | `app_factory.py:125-128` |
| `pruning.max_age` | int (h) | `24` | `24` | | `service/app_tools.py:163` — `docker image prune --filter until=<n>h` |
| `pruning.enabled` | bool | `False` | `false` | `true` | feature flag — see inventory |

### [telemetry] — TelemetrySettings (settings.py:75-77)

| Option | Type | Default | Prod | Test | Consumer |
|---|---|---|---|---|---|
| `enabled` | bool | `False` | `false` | `true` | `service/telemetry.py:19,27` — gates both request counting and sending |
| `send_interval_seconds` | int | `300` | `300` | | `app_factory.py:136`; sends to controller `api/telemetry` (`telemetry.py:38-39`) |

### [management], [freeshard_controller]

| Section.option | Default | Prod | Consumer |
|---|---|---|---|
| `management.api_url` | REQUIRED | `https://ptlfunctionapp.azurewebsites.net/api/management` (legacy Azure function app) | ONLY `service/app_usage_reporting.py:54` (monthly `/app_usage` POST). `management_mock.py` mocks this API for local dev — point at it with `FREESHARD_MANAGEMENT__API_URL`. |
| `freeshard_controller.base_url` | REQUIRED | `https://controller.freeshard.net` | `service/freeshard_controller.py:14`, `service/portal_controller.py:15` (yes — the *portal_controller module* reads the *freeshard_controller setting*), `web/protected/feedback.py:23`, `web/internal/call_backend.py:26` |

### [log] and [terminal]

| Option | Type | Default | Dev | Consumer |
|---|---|---|---|---|
| `log.levels` | dict[str,str] | `{}` | `shard_core=debug`, quiets `app_usage_reporting` + `websocket`; prod sets `gunicorn=warning` | `app_factory.py:72-75` — per-module log levels; key `root` targets the root logger; dotted keys must be quoted in TOML |
| `terminal.pairing_code_deadline` | int (s) | `600` | | `service/pairing.py:34` — pairing-code validity |
| `terminal.jwt_secret_length` | int | `64` | | `service/pairing.py:96` — `secrets.token_urlsafe` length |

`[terminal]` appears in NO TOML file — defaults only. Override via env if ever needed.

## Dead config — removed 2026-07-15

The three items below used to parse fine and do nothing. Issue #128 removed all of them; they
are recorded here so the names are recognisable in old branches, old backups, and reviews.

| Item | What it was | Why it was dead |
|---|---|---|
| `CONFIG` env var | Set in both justfile run-dev recipes, CI `test.yml`, `tests/conftest.py`, and the README | Vestige of the gconf loader that commit e2c06a7 replaced with pydantic-settings; no code ever read it. The justfile/CI values named `.yml` files that had not existed since the TOML migration. Config loading always worked anyway, because `config.toml` is unconditional and `local_config.toml` auto-overlays when present. |
| `services.backup.included_globs` | A `BackupSettings` field, populated in `config.toml` | Never wired into the rclone command; `service/backup.py` syncs the `directories` list only. |
| `[portal_controller] base_url` | A `PortalControllerSettings` model + optional `Settings` field, set in `config.toml` | Legacy of the portal→freeshard-controller migration. `service/portal_controller.py` — the module still exists and is still live — reads `settings().freeshard_controller.base_url`. |

The general lesson outlives the specific items: a config option is only real if something reads
it. Before trusting an option, grep for its consumer.

## Feature-flag inventory

| Flag | Default | Prod | What it gates | Bypass / caveat |
|---|---|---|---|---|
| `traefik.disable_ssl` | `false` | unset (false) | Static-config template `traefik_no_ssl.yml` vs `traefik.yml` (`app_factory.py:142-145`); http vs https scheme in shard URL and Traefik dynamic config (`app_factory.py:163`, `service/traefik_dynamic_config.py:42,166,216,225,233-234`) | Dev/testing only. Self-hosted exposure: `DISABLE_SSL` in `.env.template:4`. |
| `telemetry.enabled` | `false` | `false` | Both request counting and sending (`service/telemetry.py:19,27`) | `true` in tests. Sends request counts to the freeshard controller. |
| `apps.pruning.enabled` | `false` | `false` | The *scheduled* docker image prune short-circuits when disabled (`service/app_tools.py:175-176`) | Manual `POST /protected/settings/prune-images` (`web/protected/settings.py:14-19`) calls `docker_prune_images(apply_filter=False)` — it runs regardless of the flag AND ignores `max_age`. |
| Peer-to-peer | **NO FLAG EXISTS** | always active | Nothing — peers router included unconditionally (`web/protected/__init__.py:26`), `update_all_peer_pubkeys` PeriodicTask runs every 60 s (`app_factory.py:116`) | README's "peer-to-peer is disabled" means "no app uses it / not surfaced in UI", not config-gated. Don't search for a flag; there isn't one. |

## Compose / .env mapping (self-hosted surface)

`.env.template` → `docker-compose.yml:63-67` env mapping on the `shard_core` service:

| .env var | Compose mapping | Guard |
|---|---|---|
| `DNS_ZONE` | `FREESHARD_DNS__ZONE=${DNS_ZONE:?}` | fail-fast if unset |
| `EMAIL` | `FREESHARD_TRAEFIK__ACME_EMAIL=${EMAIL:?}` | fail-fast |
| `FREESHARD_DIR` | `FREESHARD_PATH_ROOT_HOST=${FREESHARD_DIR:?}` (also raw in volume mounts) | fail-fast |
| `DISABLE_SSL` | `FREESHARD_TRAEFIK__DISABLE_SSL=${DISABLE_SSL:-false}` | defaults to `false` when unset |

### Trap: an unguarded boolean crashes boot

Until 2026-07-15 (issue #128), `DISABLE_SSL` was interpolated bare as `${DISABLE_SSL}`. A
self-hoster who omitted the line from `.env` passed an **empty string** to
`FREESHARD_TRAEFIK__DISABLE_SSL`, and `Settings()` raised at startup:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
traefik.disable_ssl
  Input should be a valid boolean, unable to interpret input [type=bool_parsing, input_value='', ...]
```

It now carries a `:-false` default, so an unset var behaves like an absent one. The trap
generalises to every NEW compose env mapping you add: an empty string is not the same as
unset, so give the var a `${VAR:-default}` or a `${VAR:?}` guard. Bare `${VAR}` on a
non-string field is a boot crash waiting for the first person who skips the line.

## Committed registry credentials

`config.toml:30-33` contains a real Azure Container Registry login (`portalapps.azurecr.io`,
service-principal GUID username, plaintext password) committed to the repo. It is
`docker login`-ed at every startup (`app_installation/__init__.py:123-133`) **and at test-session
start** (`tests/conftest.py:129-131` `setup_all` fixture) — rotating or revoking these
credentials breaks the test suite. Whether committing them is intentional (scoped pull-only
token) or an oversight is unverified as of 2026-07-03. Do not copy this pattern for new
registries; do not "helpfully" delete them either — that is a change-control question
(see freeshard-change-control).

## How tests override config

Three layers, all in `tests/conftest.py`:

1. **Base**: autouse fixture `config_override` (`tests/conftest.py:134-156`) builds a
   `_TestSettings` instance per test — `config.toml` + `tests/config.toml` overlay (instead of
   `local_config.toml`), with `path_root=tmp_path/...` and the pytest-docker Postgres as init
   kwargs — and installs it via `set_settings()`; teardown calls `reset_settings()`.
2. **Per-module**: define a module-level dict named `config_override` in the test file — the
   fixture picks it up by name (`conftest.py:139`).
3. **Per-test**: `@pytest.mark.config_override({...nested dict...})` (`conftest.py:142-143`),
   or the `settings_override({...})` context manager (`conftest.py:78-88`) for a scoped block
   inside a test.

Rules: never mutate `settings()` fields directly; never instantiate plain `Settings()` in a
test. `tests/config.toml` exists to make background tasks fast (refresh_interval=2,
every-second crons) and to enable flags that default off (pruning, telemetry) so they're
exercised.

## Add-a-config-option checklist

0. **Gate**: a new config option is a behavior change — it needs a Refined issue on the Dev
   Board first (freeshard-change-control §6).
1. **Field**: add it to the right `BaseModel` in `shard_core/settings.py` with a sane default.
   Make it required (no default) only if prod MUST set it explicitly in `config.toml`.
2. **Prod value**: set in `config.toml` (required fields always; defaulted fields when prod
   differs from the default).
3. **Dev/test overlays**: `local_config.toml` if dev needs a different value; `tests/config.toml`
   if a background task consumes it (tests need fast intervals / enabled flags).
4. **Self-hosted exposure** (only if self-hosters must set it): add a documented line to
   `.env.template` and a `FREESHARD_<SECTION>__<FIELD>=${VAR:?}` mapping in `docker-compose.yml`.
   Double underscore between section and field. `:?` guard always — a boolean passed as an
   unguarded `${VAR}` crashes `Settings()` on empty string (see trap above).
5. **Verify the env path** with the one-liner (see "Verify-an-override one-liner").
6. **Wire a consumer** via `settings().<section>.<field>` and grep to confirm it's actually
   read — this repo carried two parsed-but-dead options for years; don't add a third.
7. **Before trusting an EXISTING option**, grep for its consumer first. Parsing is not proof of
   use: an option with no reader validates, documents itself, and changes nothing.

## When NOT to use this skill

- Bringing up the compose stack, dev server, releases, backup/restore →
  **freeshard-run-and-operate**.
- Recreating the dev environment, uv, worktrees, type-sync → **freeshard-build-and-env**.
- Test-suite architecture and fixtures beyond the config-override machinery →
  **freeshard-testing-and-qa**.
- Why config is designed this way / what invariants must hold →
  **freeshard-architecture-contract**.
- Debugging a running shard's misbehavior (beyond "my override doesn't land") →
  **freeshard-debugging-playbook**.
- Whether you're allowed to change prod config values or rotate the committed credentials →
  **freeshard-change-control**.

## Provenance and maintenance

Written 2026-07-03; config surface updated 2026-07-15 for issue #128, which removed the three
dead-config items, fixed the justfile single-underscore recipe, and defaulted the `DISABLE_SSL`
compose mapping. Primary sources: `shard_core/settings.py`, `config.toml`, `local_config.toml`,
`tests/config.toml`, `.env.template`, `docker-compose.yml`, `justfile`, `tests/conftest.py`,
`.github/workflows/test.yml`; commits e2c06a7 (gconf → pydantic-settings), 5de2998 (env
delimiter incident), 773f736 (local_config.toml dockerignore).

Drift-prone facts — re-verify before relying on them:

| Fact (as of 2026-07-03) | Re-verification command (repo root) |
|---|---|
| Option set / defaults in the catalog | `cat shard_core/settings.py` |
| Prod values | `cat config.toml` |
| Dev / test overlay values | `cat local_config.toml tests/config.toml` |
| Precedence: init > env > local_config.toml > config.toml | `sed -n '129,152p' shard_core/settings.py` |
| `CONFIG` / `included_globs` / `[portal_controller]` all still gone | `grep -rn "CONFIG=\|included_globs\|portal_controller" justfile .github/workflows/test.yml tests/conftest.py config.toml shard_core/settings.py` (expect empty; a hit means dead config came back) |
| justfile controller recipe still uses the double underscore | `grep -n FREESHARD_FREESHARD_CONTROLLER justfile` (broken if not `__BASE_URL`) |
| `DISABLE_SSL` compose mapping still defaulted | `grep -n DISABLE_SSL docker-compose.yml` (broken if no `:?` or `:-`) |
| ACR credentials still committed / still docker-login'd in tests | `sed -n '30,33p' config.toml; sed -n '129,131p' tests/conftest.py` |
| Feature-flag consumers unchanged | `grep -rn "disable_ssl\|telemetry.enabled\|pruning.enabled" shard_core/` |
| Peer-to-peer still unflagged | `grep -rn "peer" shard_core/settings.py` (expect empty) |
| Env override still lands | the verify-an-override one-liner |
