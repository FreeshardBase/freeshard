# Shard Core

The software running on each individual Freeshard. Manages installed apps, terminal pairing, peer communication, backups, and serves as the control plane for a user's personal cloud computer.

## Tech Stack

- **Framework**: FastAPI with uvicorn, Python 3.13+
- **Database**: TinyDB (JSON-based, embedded, thread-safe via RLock)
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
  database/           → TinyDB wrapper with context managers
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
TinyDB with context managers for thread safety. No ORM, no SQL.
```python
with installed_apps_table() as apps:
    app = apps.get(Query().name == "myapp")
    apps.update({"status": Status.RUNNING}, Query().name == "myapp")
```

Tables: `identities`, `terminals`, `installed_apps`, `peers`, `backups`, `tours`, `app_usage_track`, plus a key-value base table.

### Authentication (4 levels)
- `/public/*` — No auth
- `/protected/*` — JWT in `authorization` cookie (from terminal pairing)
- `/internal/*` — Ed25519 signature verification (for app-to-shard and peer-to-shard calls)
- `/management/*` — Management API auth (hosted shards only)

### Background Tasks
Started at app lifespan startup, stopped at shutdown:
- `InstallationWorker` — async task queue for app install/uninstall
- `PeriodicTask(control_apps, 10s)` — auto-start/stop app containers
- `PeriodicTask(update_disk_space, 3s)` — disk monitoring
- `CronTask(start_backup, "0 3 * * *")` — daily backup with random delay
- `CronTask(docker_prune_images, daily)` — image cleanup
- Various telemetry and peer key refresh tasks

### Signals (Event System)
Blinker-based decoupled events defined in `util/signals.py`:
- `on_apps_update` — app state changed
- `on_request_to_app` — user accessing app (triggers auto-start)
- `on_terminal_auth` — terminal authenticated
- `async_on_first_terminal_add` — first pairing complete

### App Installation Flow
1. Request queued → `InstallationWorker` picks it up
2. Docker Compose template rendered with Jinja2 (shard domain, data paths, etc.)
3. Traefik dynamic config generated for the app's subdomain routing
4. `docker-compose up -d` via subprocess
5. Status updated in TinyDB

### Async Fire-and-Forget
Long operations use `asyncio.create_task()` with done callbacks. No thread pools.

### Service-to-Controller Communication
`freeshard_controller.py` and `portal_controller.py` make HTTP calls to the central platform. Requests are signed with Ed25519 keys via `signed_call.py`.

## File Path Conventions

Inside Docker container:
- `/core/shard_core_db.json` — main TinyDB database
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
