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
    app_lifecycle.py    Auto-start/stop containers based on idle time
    app_tools.py        Docker CLI wrapper functions
    pairing.py          Terminal pairing (JWT creation, code generation)
    backup.py           Azure Blob Storage backup via rclone
    peer.py             Peer shard management
    crypto.py           Ed25519 key generation, signing, verification
    portal_controller.py  API calls to management portal
    freeshard_controller.py  API calls to controller
    telemetry.py        Usage metrics reporting
    disk.py             Disk space monitoring
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

### Authentication (4 levels)
- `/public/*` — No auth
- `/protected/*` — JWT in `authorization` cookie (from terminal pairing)
- `/internal/*` — Ed25519 signature verification (for app-to-shard and peer-to-shard calls)
- `/management/*` — Management API auth (hosted shards only)

### Background Tasks
Started at app lifespan startup, stopped at shutdown:
- `InstallationWorker` — async task queue for app install/uninstall
- `PeriodicTask(control_apps, 30s)` — auto-start/stop app containers
- `PeriodicTask(update_disk_space, 30s)` — disk monitoring
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
1. Request queued → `InstallationWorker` picks it up
2. Docker Compose template rendered with Jinja2 (shard domain, data paths, etc.)
3. Traefik dynamic config generated for the app's subdomain routing
4. `docker-compose up -d` via subprocess
5. Status updated in PostgreSQL

### Async Fire-and-Forget
Long operations use `asyncio.create_task()` with done callbacks. No thread pools.

### Service-to-Controller Communication
`freeshard_controller.py` and `portal_controller.py` make HTTP calls to the central platform. Requests are signed with Ed25519 keys via `signed_call.py`.

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

## Important Notes

- The `Status` enum in `app_meta.py` covers the full app lifecycle: UNKNOWN, INSTALLATION_QUEUED, INSTALLING, STOPPED, RUNNING, DOWN, etc.
- `VMSize` enum (XS, S, M, L, XL) has comparison operators — used to check if a shard is large enough for an app.
- Docker socket is mounted read-write (`/var/run/docker.sock`) — shard_core manages containers directly.
- Traefik routes app traffic via subdomains: `<app-name>.<shard-domain>`.
- The project was formerly called "Portal" — some references may still use the old name.
