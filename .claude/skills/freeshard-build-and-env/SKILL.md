---
name: freeshard-build-and-env
description: Set up and verify a working shard_core development environment. Use when starting from a fresh clone or bare machine, creating a git worktree for an issue, running uv sync, wondering what a justfile recipe does (run-dev, cleanup, get-types, set-version, run-from-backup), reading the Dockerfile, or hitting env-shaped failures (import errors, "config.toml not found", pytest can't bind port 5433, docker network 'portal' already exists, black/ruff not found). TRIGGER on: "set up the repo", "uv sync", ".worktrees", "justfile", "just cleanup", "Dockerfile", "CI installs differently than local", fresh-environment smoke test. SKIP when: actually running the shard or the compose stack, dev server usage, backup/restore ops (use freeshard-run-and-operate); writing or debugging tests and fixtures (use freeshard-testing-and-qa); type-sync policy and controller drift details (use freeshard-ecosystem-contracts); config keys and env-override semantics (use freeshard-config-and-flags).
---

# Freeshard build & environment

Goal: from a bare Linux box (or a fresh worktree) to a state where `pytest` collects, `ruff` passes, and you can trust your results. Repo = **shard_core**, the FastAPI backend that runs on each Freeshard VM ("shard") and orchestrates user apps via Docker Compose behind Traefik.

All commands assume CWD = repo root (`/home/ubuntu/projects/freeshard/freeshard` on the main dev VM; adjust for your clone/worktree).

## When NOT to use this skill

| You want to... | Use instead |
|---|---|
| Run the dev server, bring up the compose stack, first-start pairing, backup/restore, release | freeshard-run-and-operate |
| Understand/extend the test suite, fixtures, flaky tests | freeshard-testing-and-qa |
| Sync types from the controller, cross-repo contracts, drift checks | freeshard-ecosystem-contracts |
| Look up a config key, env override rules, dead config | freeshard-config-and-flags |
| Know what changes are allowed and how they ship | freeshard-change-control |

## Prerequisites

| Tool | Required | On the main dev VM as of 2026-07-03 | Check |
|---|---|---|---|
| Python | >= 3.13 (`pyproject.toml:15`) | 3.13.3 | `python3 --version` |
| uv | any recent | 0.10.7 | `uv --version` |
| just | any recent | 1.40.0 | `just --version` |
| Docker daemon | running, socket accessible | 29.2.1 | `docker info >/dev/null && echo ok` |
| Docker Compose | **v2 plugin** (`docker compose`, not `docker-compose`) | v5.0.2 | `docker compose version` |
| gh | authenticated | 2.46.0 | `gh auth status` |
| Internet | yes — tests do a real `docker login` + real image pulls | — | — |

uv can provision Python itself (`uv python install 3.13`) if the system Python is too old. Docker + internet are needed even for "just running the tests": the test suite starts a real postgres:17 container and logs into a real container registry (see traps below).

## From bare Linux to productive

```bash
git clone https://github.com/FreeshardBase/freeshard.git
cd freeshard
uv sync --extra dev            # creates .venv from uv.lock; --extra dev pulls pytest, ruff, etc.
.venv/bin/pytest tests --collect-only -q   # expect "137 tests collected" (origin/main as of 2026-07-03; 134 on the older e55ce51 checkout — count drifts, cross-check freeshard-testing-and-qa), zero errors
.venv/bin/ruff check .         # expect no findings on a clean main
```

Notes:

- `uv sync` installs from **uv.lock** — the single source of truth for dependency versions. Never `pip install .` into this venv.
- Dev tools live in the optional extra `[project.optional-dependencies].dev` (pyproject.toml:47-59). Without `--extra dev` you get no pytest/ruff.
- `black` is **not** listed in the dev extra, but `just cleanup` calls `.venv/bin/black`. It works anyway because black is a transitive dependency of `datamodel-code-generator` (see uv.lock). If `just cleanup` ever reports black missing, you ran `uv sync` without `--extra dev`.
- The `shard_core.egg-info/` directory you may see at repo root is a setuptools build artifact, gitignored — ignore it.

## Worktree discipline (mandatory for new work)

Convention in this repo: every feature/bugfix gets its own worktree under `.worktrees/<slug>` on its own branch, cut from **freshly pulled** `origin/main`. The overnight agent loop assumes this; parallel sessions must not share a checkout.

```bash
git fetch origin main
git worktree add .worktrees/<slug> -b <branch-name> origin/main
cd .worktrees/<slug>
uv sync --extra dev            # ALWAYS, before anything else
.venv/bin/pytest tests --collect-only -q   # sanity: env works
```

Rules:

- **ALWAYS run `uv sync --extra dev` inside the new worktree.** Never symlink or share `.venv` from the main checkout: branches can diverge on `pyproject.toml`/`uv.lock`, and a borrowed venv gives silently wrong test results and pollutes the other checkout with `__pycache__` writes.
- `.worktrees/` is ignored via `.git/info/exclude` (local-only; **not** committed in `.gitignore`). In a fresh clone, add it yourself: `echo '.worktrees/' >> .git/info/exclude`.
- Two worktrees **cannot run the test suite at the same time** — see traps (port 5433, compose project name, docker network `portal` are all host-global).
- `local_config.toml` is committed, so every worktree has it — but it is resolved relative to CWD (see traps). Run everything from the worktree root.

## Repo layout orientation map

```
freeshard/                     repo root (package name: shard_core)
├── shard_core/                the Python package
│   ├── app.py                 entrypoint (target of `fastapi run/dev`)
│   ├── app_factory.py         create_app() + lifespan = startup/shutdown order
│   ├── settings.py            pydantic-settings: config.toml + local_config.toml + FREESHARD_* env
│   ├── web/                   FastAPI routers by auth level: public/ protected/ internal/ management/
│   ├── service/               business logic (app_installation/, backup.py, crypto.py, ...)
│   ├── database/              psycopg3 async access layer (yoyo migrations applied at startup)
│   ├── data_model/            pydantic models; backend/ = COPIED from controller — never hand-edit
│   └── util/
├── data/                      runtime templates: traefik.yml(+_no_ssl), welcome-log jinja, splash.html, EFF wordlist
├── migrations/                yoyo SQL migrations (shard-core-0001-init.sql)
├── tests/                     pytest suite; tests/config.toml = overlay; tests/docker-compose.yml = postgres:17 on :5433
├── scripts/                   generate_traefik_dyn_config_model.py — raises on purpose, do NOT run (hand-patched output)
├── config.toml                base config, committed (contains live ACR pull credentials — do not "clean up")
├── local_config.toml          dev overlay: path_root="run/", dns.zone="localhost" (CWD-relative, dockerignored)
├── docker-compose.yml         production stack: postgres + traefik + shard_core + web-terminal on network 'portal'
├── Dockerfile                 two-stage uv image build (see anatomy below)
├── justfile                   task recipes (see anatomy below)
├── uv.lock                    dependency source of truth (CI and image both build --frozen from it)
└── .worktrees/                per-task worktrees (ignored via .git/info/exclude)
```

## justfile recipe anatomy

Verified against `justfile` as of 2026-07-03. `just` (no args) lists recipes.

| Recipe | What it actually does | Gotchas |
|---|---|---|
| `just run-dev` | `fastapi dev --port 8080 shard_core/app.py` via `.venv/bin/fastapi`, with `PYTHONUNBUFFERED=1` | Config comes from `config.toml` plus `local_config.toml` if present, picked up by settings.py automatically. Usage details: freeshard-run-and-operate. |
| `just run-dev-for-freeshard-controller` | second dev instance on port 8081, *intended* to point at a local controller on 8080 | Sets `FREESHARD_FREESHARD_CONTROLLER__BASE_URL=http://127.0.0.1:8080`. Until issue #128 this was a single underscore, which pydantic-settings silently ignored — the instance talked to the **production** controller. See freeshard-config-and-flags. |
| `just cleanup` | `ruff check . --fix` then `black shard_core` and `black tests` | **Run after every code change** — it is the house formatting gate. Requires the dev extra installed (black is transitive). |
| `just get-types` | **DESTRUCTIVE**: `rm -rf shard_core/data_model/backend`, then `cp -r` from the **LOCAL** sibling checkout `../freeshard-controller/freeshard-controller-backend/freeshard_controller/data_model`, prepending `# DO NOT MODIFY` to every file | Syncs from whatever your local controller checkout happens to be at. **You MUST `git -C ../freeshard-controller checkout main && git -C ../freeshard-controller pull` first.** A stale checkout has caused real bugs before (silently dropped billing fields — commits 6d4b101, e55ce51). As of 2026-07-03 the local controller checkout on the dev VM was verified BEHIND origin/main. Full procedure and drift checks: freeshard-ecosystem-contracts. |
| `just set-version X.Y.Z` | rewrites `version` in pyproject.toml and the `ghcr.io/freeshardbase/freeshard:` tag in docker-compose.yml, then **`git add .` and `git commit`** | It stages EVERYTHING (`git add .`) — never run with a dirty tree. Release procedure: freeshard-change-control / freeshard-run-and-operate. |
| `just run-from-backup <zip>` | **DESTRUCTIVE**: `rm -rf run/` then unzips the backup into `run/` (the dev `path_root`) | Wipes local dev state without asking. Restore workflow: freeshard-run-and-operate. |

## Dockerfile anatomy (why the image looks like that)

Two-stage build, verified against `Dockerfile` as of 2026-07-03:

1. **Build stage** — `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`. Runs `uv sync --frozen --no-install-project --no-dev` first (dependencies only, cached layer), then `ADD . .` + `uv sync --frozen --no-dev` (project itself). `UV_COMPILE_BYTECODE=1`, uv cache mounts. `--frozen` = build exactly from uv.lock.
2. **Runtime stage** — `python:3.13-slim-bookworm` plus:
   - `curl` — used by the container HEALTHCHECK (`curl -f http://localhost/public/health`).
   - `rclone` — the backup engine (rclone crypt → Azure Blob).
   - `tini` as PID 1 (`ENTRYPOINT ["/usr/bin/tini","--"]`) — reaps the zombie processes the healthcheck curl otherwise leaves behind (https://github.com/FreeshardBase/freeshard/pull/55).
   - **Full Docker install via get.docker.com** — shard_core drives its sibling app containers by shelling out to `docker`/`docker compose` against the docker.sock mounted from the host (docker-compose.yml mounts `/var/run/docker.sock`). Only the CLI + compose plugin are used; the daemon inside the image never runs.
   - `CMD ["fastapi","run","--port","80","shard_core/app.py"]`.

## CI parity rule

**Install from the lockfile, exactly like CI and the image do.** As of 2026-07-03, `.github/workflows/test.yml` on origin/main installs with `uv sync --frozen --extra dev` and runs `uv run ruff check .` / `uv run pytest tests` (changed in https://github.com/FreeshardBase/freeshard/pull/114). Before that, CI used `pip install ".[dev]"`, which ignores uv.lock and resolves latest-at-runtime — a fresh upstream release broke the controller's CI that way with zero code changes, and this repo switched preemptively. If you see red CI with no plausible connection to the diff, first check whether the install step still honors the lock.

Match CI locally:

```bash
uv sync --frozen --extra dev   # exactly what CI installs
uv run ruff check .            # CI lint job
uv run pytest tests            # CI test job (needs Docker + internet)
```

`uv sync` without `--frozen` will also *update* uv.lock if pyproject.toml changed — fine during development, but a lockfile diff you didn't intend belongs out of your PR.

One workflow variable is dead but still present (do not cargo-cult it): `TEST_ENV=full/sparse` — its consumer was removed, so push and PR runs are identical. A companion dead `CONFIG=tests/config.yml` was removed by issue #128.

## Known traps

| Trap | Reality | Evidence |
|---|---|---|
| `local_config.toml` silently not applied | It is resolved via `Path("local_config.toml").exists()` — **relative to CWD**. Run the server/tests from the repo (or worktree) root, or your dev overlay (path_root=`run/`, dns.zone=localhost) vanishes and the app tries production paths. Also listed in `.dockerignore`, so it can never leak into the image — don't try to configure the container with it. | settings.py:148-152; .dockerignore |
| Tests "just need pytest" | They need a running Docker daemon, compose v2, and internet: a session fixture does a **real `docker login`** to `portalapps.azurecr.io` using credentials committed in `config.toml:30-33`, and app-installation tests really pull images from that registry. If those credentials are ever rotated, api_client-based tests fail on pulls — that is an infra failure, not your bug. | tests/conftest.py:129-131 |
| Concurrent test runs collide | tests/docker-compose.yml pins host port **5433** and conftest pins compose project name **`shard-core-test`**. Two worktrees running pytest simultaneously fight over both. Run suites serially across worktrees. | tests/docker-compose.yml:9; tests/conftest.py:96-98 |
| Docker network `portal` and container names are host-global | The production compose stack, a locally running dev shard, and the test suite all use the network name `portal` and fixed container names (`postgres`, `traefik`, `shard_core`, app names like `filebrowser`). Test teardown force-removes the `portal` network — it will rip it out from under a dev shard running on the same host. | docker-compose.yml:1-3; tests/util.py:139-147 |
| `scripts/generate_traefik_dyn_config_model.py` | Raises `Exception("Do no use! ...")` at import, deliberately: its output model was hand-patched (`authResponseHeadersRegex`) and regenerating would drop that field. Do not "fix" the script. | scripts/generate_traefik_dyn_config_model.py |
| Leftover test infra after a crash | A killed pytest run leaves the test postgres and/or `portal` network behind; the next run fails on port/name conflicts. | Cleanup: `docker compose -p shard-core-test -f tests/docker-compose.yml down -v` and `docker network rm portal` |

## 15-minute smoke checklist (fresh environment)

Run top to bottom; each step has a pass condition. Stop and fix at the first failure.

```bash
# 1. Toolchain present (~1 min)
python3 --version && uv --version && just --version && gh auth status
docker info >/dev/null && docker compose version        # daemon up, compose v2

# 2. Clean, current source (~1 min)
git fetch origin main && git status                      # expect: clean tree
git log --oneline -1 origin/main                         # note the tip you're building against

# 3. Env from lockfile (~2 min)
uv sync --frozen --extra dev                             # pass: exits 0, no resolver output

# 4. Package imports (~10 s)
.venv/bin/python -c "import shard_core.app_factory; print('import ok')"
# pass: prints "import ok" (a CryptographyDeprecationWarning about OFB is known noise as of 2026-07-03)

# 5. Test collection (~30 s, no Docker yet)
.venv/bin/pytest tests --collect-only -q | tail -1       # pass: "N tests collected", zero errors (137 on origin/main as of 2026-07-03; the count drifts — what matters is zero collection errors)

# 6. Lint (~10 s)
.venv/bin/ruff check .                                   # pass: "All checks passed!"

# 7. One real test — exercises pytest-docker, postgres:17 spin-up on :5433,
#    internet, and the committed ACR docker login (~3-5 min)
.venv/bin/pytest tests/test_crypto.py -q                 # pass: all green

# 8. Formatting gate works (~30 s)
just cleanup && git status                               # pass: exits 0; tree still clean on untouched main
```

If step 7 fails at container startup: check for a leftover `shard-core-test` compose project or occupied port 5433 (traps table). If it fails at `docker login` or image pull: the committed ACR credential may be rotated — escalate rather than debug your own change.

## Provenance and maintenance

Written 2026-07-03 against branch state `origin/main` @ 0a40684 (local checkout on `fix-profile-billing-fields` @ e55ce51). Primary sources: `justfile`, `Dockerfile`, `pyproject.toml`, `uv.lock`, `shard_core/settings.py`, `tests/conftest.py`, `tests/docker-compose.yml`, `docker-compose.yml`, `.github/workflows/test.yml` (origin/main), `README.md`, https://github.com/FreeshardBase/freeshard/pull/114, https://github.com/FreeshardBase/freeshard/pull/55. Tool versions quoted are the main dev VM's on the same date.

Drift-prone facts — re-verify before trusting:

| Fact (as of 2026-07-03) | Re-verify with |
|---|---|
| Version 0.39.2 / image tag in compose | `grep '^version' pyproject.toml && grep 'freeshardbase/freeshard:' docker-compose.yml` |
| 137 tests collected (origin/main; 134 at e55ce51) | `.venv/bin/pytest tests --collect-only -q \| tail -1` |
| CI installs via `uv sync --frozen --extra dev` | `git fetch origin && git show origin/main:.github/workflows/test.yml \| grep -A3 'Install dependencies'` |
| dev extra contents / black still transitive | `grep -A12 'dev = \[' pyproject.toml` |
| Test postgres port 5433 / project `shard-core-test` | `grep 5433 tests/docker-compose.yml && grep -n 'shard-core-test' tests/conftest.py` |
| ACR creds still committed & logged into | `grep -n 'azurecr' config.toml && grep -n 'login_docker_registries' tests/conftest.py shard_core/service/app_installation/__init__.py` |
| Local controller checkout current before get-types | `git -C ../freeshard-controller rev-parse HEAD && git -C ../freeshard-controller ls-remote origin main` (hashes must match) |
| `.worktrees/` excluded locally | `grep worktrees .git/info/exclude` |
| Crypto still RSA-4096/PSS | `grep -n 'generate_private_key\|key_size\|RSA_PSS' shard_core/service/crypto.py shard_core/service/signed_call.py` |
| tini/docker/rclone still in runtime image | `grep -n 'tini\|get.docker.com\|rclone' Dockerfile` |
