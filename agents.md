# Shard Core

The software running on each individual Freeshard. Manages installed apps, terminal pairing, peer communication, backups, and serves as the control plane for a user's personal cloud computer.

## Tech Stack

- **Framework**: FastAPI with uvicorn, Python 3.13+
- **Database**: PostgreSQL with psycopg3 (async) + yoyo-migrations
- **Container Orchestration**: Docker / Docker Compose (subprocess calls)
- **Reverse Proxy**: Traefik v3 (configured dynamically per app)
- **Config**: Pydantic v2 BaseSettings, loaded from `config.toml` + `local_config.toml`, env prefix `FREESHARD_`
- **Package Management**: uv
- **Formatting/Linting**: ruff + black
- **Testing**: pytest + pytest-asyncio + pytest-docker

## Architecture

```
shard_core/
  web/                → FastAPI routers, organized by auth level
    public/             No auth required (meta, health, pairing)
    protected/          JWT auth from paired terminal (apps, settings, backup, etc.)
    internal/           Same-machine auth via signatures (app→backend, app→peer calls)
    management/         Management API auth (hosted shards only)
  service/            → Business logic
    app_installation/   App install/uninstall/reinstall + background worker queue
    app_lifecycle.py    Two-tier idle control: RUNNING -> PAUSED -> STOPPED, PSI-driven LRU demotion, wake-on-request
    app_tools.py        Docker CLI wrapper functions (start/stop/pause/unpause/down)
    memory_pressure.py  PSI parsing (/host/pressure/memory), cgroup v2 memory.reclaim page-out
    pause_metrics.py    In-memory pause-tier telemetry accumulators (transitions, latencies, PSI snapshots)
    pairing.py          Terminal pairing (JWT creation, code generation)
    backup.py           Azure Blob Storage backup via rclone
    peer.py             Peer shard management
    crypto.py           RSA-4096 key generation, signing, verification (PSS padding)
    portal_controller.py  API calls to management portal
    freeshard_controller.py  API calls to controller
    telemetry.py        Usage metrics reporting
    disk.py             Disk space monitoring
    disk_full_notification.py  Owner email when disk crosses threshold (via controller relay, deduped)
    migration.py        Database schema migrations
    websocket.py        WebSocket connection lifecycle
  database/           → PostgreSQL access layer (per-entity modules, conn-first-arg pattern)
  data_model/         → Pydantic v2 models
    app_meta.py         App metadata, Status enum, VMSize enum
    identity.py         Shard identity (keys, domain, short_id)
    terminal.py         Paired device models
    peer.py             Peer shard models
    backend/            Models copied from freeshard-controller (via `just get-types`)
  util/               → Shared utilities
    async_util.py       BackgroundTask, PeriodicTask, CronTask
    signals.py          Blinker signal definitions
    subprocess.py       Async subprocess runner; app_compose_command() pins every app
                        compose call to <app_dir>/docker-compose.yml and project <app>
                        — never rely on cwd, compose walks up to the core stack
```

## Commands

```bash
just run-dev          # FastAPI dev server on port 8080, loads local_config.toml
just cleanup          # ruff check + black formatting
just get-types        # Sync data models from freeshard-controller repo
```

## Key Patterns

### Database Access
PostgreSQL via psycopg3 async. All DB functions take `conn: AsyncConnection` as first arg. Callers acquire connections via `async with db_conn() as conn:`. Schema managed by yoyo-migrations in `migrations/`.
```python
async with db_conn() as conn:
    app = await db_installed_apps.get_by_name(conn, "myapp")
    await db_installed_apps.update_status(conn, "myapp", Status.RUNNING)
```

Tables: `identities`, `terminals`, `installed_apps`, `peers`, `backups`, `tours`, `app_usage_tracks`, `kv_store`.

Postgres data is not part of the rclone backup set (which only syncs `core/`/`user_data/`). To keep it, `database/db_snapshot.py` dumps all application tables to `core/db_snapshot.json` before each backup, and `init_database()` restores it on a fresh shard (before the default identity is generated, so the restored identity survives). Pre-0.38 backups are restored from TinyDB by `tinydb_migration.py` instead.

### Authentication (4 levels)
- `/public/*` — No auth
- `/protected/*` — JWT in `authorization` cookie (from terminal pairing)
- `/internal/*` — HTTP Message Signature verification, `RSA_PSS_SHA512` (for app-to-shard and peer-to-shard calls)
- `/management/*` — Management API auth (hosted shards only)

### Background Tasks
Started at app lifespan startup, stopped at shutdown:
- `InstallationWorker` — async task queue for app install/uninstall
- `PeriodicTask(control_apps, 30s)` — app idle lifecycle. With `apps.lifecycle.pause_enabled` (default off): RUNNING pauses after `idle_for_pause` (cgroup freeze + page-out to swap), PAUSED stops after `idle_for_stop`, and high memory PSI demotes the LRU app one tier per cycle. Flag off: legacy stop-only
- `PeriodicTask(update_disk_space, 30s)` — disk monitoring; also triggers `disk_full_notification.check_disk_full` (owner email when usage ≥ `event_notifications.disk_full.threshold_percent`, default 90%, deduped via kv_store, opt-out via `event_notifications.disk_full.enabled`)
- `CronTask(start_backup, "0 3 * * *")` — daily backup with random delay
- `CronTask(docker_prune_images, daily)` — image cleanup
- Various telemetry and peer key refresh tasks

### Signals (Event System)
Blinker-based async signals defined in `util/signals.py`. DB-writing handlers are async and called via `await signal.send_async()`:
- `on_apps_update` — app state changed
- `on_request_to_app` — user accessing app (triggers auto-start)
- `on_terminal_auth` — terminal authenticated
- `async_on_first_terminal_add` — first pairing complete
- `async_on_peer_write` — peer added/updated

### App Installation Flow
0. Custom-app uploads (`POST /protected/apps`) are validated by `app_installation/app_zip.py` **before** any state is created: the zip is buffered to a temp dir, must carry `app_meta.json` + `docker-compose.yml.template` at its root (a single top-level directory is stripped), and the app name comes from the manifest, not the filename. Invalid uploads get a 400 and leave no row, no dir, no task. Extraction goes through `extract_app_zip`, which refuses members resolving outside the app dir.
1. Request queued → `InstallationWorker` picks it up
2. Docker Compose template rendered with Jinja2 (shard domain, data paths, etc.)
3. Traefik dynamic config generated for the app's subdomain routing
4. `docker-compose up -d` via subprocess
5. Status updated in PostgreSQL

The task queue is in-memory only, so a restart loses whatever it held. Uninstall is
made crash-safe by `reconcile_interrupted_uninstalls()`, a lifespan step that
re-enqueues an uninstall for every row still in `UNINSTALLATION_QUEUED` or
`UNINSTALLING`. `_uninstall_app` asserts no status and tolerates missing files, so
resuming it is idempotent — the row is the tombstone. The step only enqueues; the
worker starts later in the lifespan, and awaiting task completion before then
deadlocks. Install and reinstall have no equivalent reconciliation yet.

Apps in `NOT_ROUTABLE_STATUS` (`app_installation/util.py`) get no Traefik router:
`INSTALLATION_QUEUED`, `ERROR`, `UNINSTALLATION_QUEUED`, `UNINSTALLING`. Their files
are either not there yet or already being removed, and `write_traefik_dyn_config`
runs inside the lifespan — an unfiltered status whose metadata is missing raises
`MetadataNotFound` and takes down the boot.

### Async Fire-and-Forget
Long operations use `asyncio.create_task()` with done callbacks. No thread pools.

### Service-to-Controller Communication
`freeshard_controller.py` and `portal_controller.py` make HTTP calls to the central platform. Requests are signed with the shard's RSA key via `signed_call.py`, using HTTP Message Signatures with `RSA_PSS_SHA512`.

## File Path Conventions

Inside Docker container:
- PostgreSQL database (configured via `[db]` section in config.toml)
- `/core/installed_apps/{name}/` — per-app Docker Compose files
- `/core/traefik.yml` — Traefik static config
- `/user_data/app_data/{name}/` — per-app persistent data
- `/user_data/shared/` — shared data across apps

Host-side: `settings().path_root_host` (typically `/home/shard`).

## Pydantic Conventions

- `BaseModel` for data classes, `BaseSettings` for configuration
- `@field_validator` for single-field, `@model_validator(mode="after")` for cross-field
- `@computed_field` @property for derived values (e.g., `Identity.domain`, `Identity.public_key`)
- Models in `data_model/backend/` are copied from freeshard-controller — do not edit directly, use `just get-types`
  - The CI `drift-check` job re-runs `get-types` against controller **`origin/main`** and fails if the diff is non-empty. To fix drift: check out the controller at `origin/main` (a local `main` may be many commits behind — `git fetch` first), then run `just SOURCE_DIR=<abs path to controller>/freeshard-controller-backend/freeshard_controller/data_model get-types` from this repo and commit only the regenerated files. Never hand-edit them.

## Important Notes

- The `Status` enum in `app_meta.py` covers the full app lifecycle: UNKNOWN, INSTALLATION_QUEUED, INSTALLING, STOPPED, RUNNING, DOWN, etc.
- `VMSize` enum (XS, S, M, L, XL) has comparison operators — used to check if a shard is large enough for an app.
- Docker socket is mounted read-write (`/var/run/docker.sock`) — shard_core manages containers directly.
- Traefik routes app traffic via subdomains: `<app-name>.<shard-domain>`.
- The project was formerly called "Portal" — some references may still use the old name.
