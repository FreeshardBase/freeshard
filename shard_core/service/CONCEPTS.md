# Service concerns: concepts

The flat concerns of `shard_core/service/` share this file, one section each, in the order of the root module map, added as each concern is worked through; Terminals and pairing and the OIDC provider are not written yet. The repo-wide theory, including the invariants these sections refer to as "root", is in the root `CONCEPTS.md`.

## App runtime

App runtime is the only code that operates an installed app's containers and the only code that moves an app among the four statuses an app rests in between installation tasks (`RUNNING`, `PAUSED`, `STOPPED`, `DOWN`, the code's `_REVIVABLE_STATUS`): it revives an app when it is opened and on the control tick, pauses and stops idle apps, demotes one app per tick under memory pressure, takes every app down when the core stops, and provides the create and teardown primitives Installation calls.

### Files

`app_tools.py` holds the docker primitives. It also hosts three things other modules import that change no container: the manifest reader (`get_installed_apps_path`, `get_app_metadata`, `MetadataNotFound`, `enrich_installed_app_with_meta`), the size and version predicates that the start gate and the splash share, and the image prune. `app_lifecycle.py` holds the wake-on-access receiver and the control tick. `memory_pressure.py` reads memory pressure and pages a frozen stack out to swap. `pause_metrics.py` holds the accumulators for the **pause tier**, the `PAUSED` step between `RUNNING` and `STOPPED` that `apps.lifecycle.pause_enabled` switches on (#81). The file is kept apart from `telemetry.py` so that recording a transition does not import the controller client, whose import chain is cyclic.

Every compose call on an app goes through `util/subprocess.app_compose_command`, pinned to that app's compose file and project. The docker calls outside this module leave app containers untouched: the metrics sampler's `docker ps`, the splash and `call_peer` reading through the Docker SDK, and the registry login.

### Which statuses the runtime writes, and over what

The runtime writes only the four revivable statuses, and a write lands only on a row that still holds the status the operation was gated on. Every other status belongs to Installation. Installation takes a row by writing one of its statuses (an uninstall or reinstall request is accepted whatever the row holds) and hands it back by writing `STOPPED` at the end of an install or reinstall, by deleting it, or by leaving it in `ERROR`. Installation's statuses are its record of work in flight: the boot-time reconciliation reads them (the root invariant *Work that must survive a restart is a row*), and the worker's install and reinstall tasks refuse to start unless the row reads `INSTALLATION_QUEUED` or `REINSTALLATION_QUEUED`. A runtime write over one of them loses that record: a restart no longer resumes the work, and a reinstall still waiting in the queue is rejected when its turn comes. `UNKNOWN` is the model's default value; only the TinyDB import writes it.

```mermaid
stateDiagram-v2
    direction LR
    state "Installation's statuses" as Inst
    note right of Inst
        Entered from any status when an
        uninstall or reinstall is requested
    end note
    Inst --> STOPPED: install or reinstall done
    STOPPED --> RUNNING: revive (compose up)
    DOWN --> RUNNING: revive (compose up)
    PAUSED --> RUNNING: revive (compose unpause)
    RUNNING --> PAUSED: idle past T1, or pressure
    PAUSED --> STOPPED: idle past T2, pressure, low disk
    RUNNING --> STOPPED: idle past T2 without the pause tier, pressure on a skip_pause app, low disk
    RUNNING --> DOWN: core stops
    PAUSED --> DOWN: core stops
    STOPPED --> DOWN: core stops
    ERROR --> DOWN: core stops (the retry)
```

A clean stop of the core also returns a row in `ERROR` to `DOWN` when its app still has a compose file. That is `ERROR`'s intended retry (root, *An app's status has one owner*), and the one write over a status outside the four revivable ones that the runtime is meant to make.

Three paths break the write rule today. The core's stop writes `DOWN` over every row whose app directory still holds a compose file, whatever its status, Installation's in-flight statuses included. `_uninstall_app` lets `docker_stop_app` and `docker_shutdown_app` write `STOPPED` and then `DOWN` over its own `UNINSTALLING` row before it deletes the row, and the tick's low-disk stop writes `STOPPED` over an `UNINSTALLING` row the same way. And every runtime write is an unconditional `UPDATE` issued after a docker call that can take seconds, so a status Installation writes in the meantime is overwritten.

The operations this module gates, and what decides how each one acts:

| Operation | Acts when the row holds | How it acts is decided by |
| --- | --- | --- |
| Revive, `start_app` | `RUNNING`, `PAUSED`, `STOPPED`, `DOWN` | The daemon's view of the containers |
| Pause, `docker_pause_app` | `RUNNING` | Nothing further |
| Unpause, `docker_unpause_app` | `PAUSED` | Nothing further |
| Stop, `docker_stop_app` | `RUNNING`, `PAUSED`, `UNINSTALLING` | The daemon, for the unfreeze before the stop |
| Down, `docker_shutdown_app` | `STOPPED`, `UNINSTALLING`, or any status with `force` | The daemon, for the unfreeze before the down |
| The control tick | Every row except `INSTALLATION_QUEUED` and `INSTALLING` | The tick's own snapshot, re-gated by each operation |

The row decides whether an operation may run; the daemon decides how a revive or a teardown acts (#185, #199). The status-to-operation mapping as a whole is one concept with one owner (root, *An app's status has one owner*).

### The revive

`start_app` is the only code that starts or wakes an app. Wake-on-access and the `always_on` branch of the control tick are its only callers. It acts only on a revivable row and then dispatches on the containers' real state. A running stack is left alone, and the row is set to `RUNNING` if it said otherwise. A paused stack is unpaused; if the unpause fails (some containers already exited), the revive falls back to `compose up -d`. Any other stack (exited, never started, or without containers) is brought up with `compose up -d`. Every path that acts ends with the row at `RUNNING` and an `on_apps_update` announcement. A revive is idempotent: on a running stack with a `RUNNING` row it does nothing. `_compose_up` recovers from two failures the Docker CLI reports by message text, a stale network reference (d66d889) and a container name already in use (#63), by running `compose down` and then `up -d` again.

A revive holds the per-app lock that Installation's uninstall and reinstall also hold across their teardown, so a revive can never recreate containers an uninstall or reinstall has just removed (#185). It runs at most once per five seconds per app: `@throttle(5)` is keyed on the app name (5c46231) and drops a call inside the window without retrying it, so a dropped revive waits for the next request, or for the next tick if the app is `always_on`. The throttle is what bounds the cost of waking an app. Every admitted request spawns a revive task, and without the throttle a page load of thirty parallel requests would start thirty compose processes. The revive reads the row fresh on every call that passes the throttle.

`ensure_app_is_running` is a receiver of `on_request_to_app`, which `/internal/auth` sends after it has admitted a request, and the handler awaits its receivers. Everything the receiver does before it spawns the revive task therefore runs on the auth path and is bound by the root invariant *The auth path does no per-request database work*. Today it is not met: while disk is not low, `size_is_compatible` reads the profile from `kv_store` through the pool on every admitted request. The receiver and the tick's `always_on` branch are two of the three sites of the root invariant *An app is started only where it can run*; the receiver refuses to revive on low disk, on a shard too small for the app, and on a shard too old for it. It records the access in `last_access_dict` only when those checks pass. That dictionary is the tick's idle clock; it lives in the process only (root, *Work that must survive a restart is a row*, and #133).

### The control tick

`control_apps` runs in a loop with `apps.lifecycle.refresh_interval` seconds between passes. It reads every row except those in `INSTALLATION_QUEUED` or `INSTALLING` once, runs one pass per app concurrently, and then makes at most one pressure demotion. A pass decides on the snapshot, and each operation it calls re-reads the row and re-applies its own gate, so a stale snapshot can cost an action but cannot cause one the row no longer permits.

Within one app's pass the order is fixed. Low disk stops the app and ends the pass; it applies to `always_on` apps too. An `always_on` app is then handed to `start_app` on every tick, provided the size and version predicates pass. Because the revive dispatches on the real state, an `always_on` app whose row says `RUNNING` while its containers are gone comes back without anyone opening it (#239). Every other app is placed by its idle time against two thresholds. T1, the pause threshold, is the manifest's `lifecycle.idle_for_pause` or `apps.lifecycle.default_idle_for_pause`. T2, the stop threshold, is the manifest's `lifecycle.idle_for_stop` or `apps.lifecycle.default_idle_for_stop`. With `apps.lifecycle.pause_enabled` off, or for an app that declares `skip_pause`, a `RUNNING` app is stopped at T2. With the flag on, a `RUNNING` app is paused at T1 and a `PAUSED` app is stopped at T2; #227 proposes dropping the timed stop of a paused app and leaving that transition to pressure alone. The manifest validator requires T1 below T2 only when the manifest sets both, so an app with an explicit T1 above the global T2 pauses at T1 and stops one tick later (#226).

With the flag off no code pauses an app, and the idle pass never stops a `PAUSED` row: such a row waits for a request, for low disk, or for the core's stop. That is the backout behaviour #145 chose for switching the tier off. Because the flag reaches shard_core through its environment, switching it also restarts the core, and a clean stop takes every app down.

Under memory pressure, with the flag on and the [PSI](https://docs.kernel.org/accounting/psi.html) `some avg10` value of `/host/pressure/memory` above `apps.lifecycle.psi_threshold`, the tick demotes one app by one tier and leaves the rest to the next tick, so a spike frees memory gradually. The victim is the [least recently used](https://en.wikipedia.org/wiki/Cache_replacement_policies#LRU) app, chosen among `RUNNING` apps first and among `PAUSED` apps only when no running candidate is left; pausing costs a user less than stopping, and paused apps would otherwise mostly look least recently used. `always_on` apps are never demoted. Neither is an app accessed within `RECENT_ACCESS_GRACE`, five seconds. A `RUNNING` victim that declares `skip_pause` is stopped. The grace must not be shorter than the revive throttle's window: an app demoted inside that window would have its next revive dropped, and the request would wait on a frozen stack.

An app whose manifest the tick cannot read must not cost the shard its demotion (root, *One app's unreadable manifest costs only that app*), because the demotion is what the pause tier relies on to free memory when the host runs short. The code does not meet this yet (#280): each pass and the demotion read the app's manifest first, the per-app passes run under an `asyncio.gather` without `return_exceptions`, and a single row without a readable `app_meta.json` (an `ERROR` row whose download failed, a reinstall that failed after deleting the old files) makes every tick end before the demotion, while the other apps' passes still run. `write_traefik_dyn_config`, which reads the same manifests, skips such an app with a warning.

### Pausing and paging out

A pause freezes the stack with `compose pause` and then pages its memory out. For each container `compose ps` lists, it writes the container's `memory.current` to the cgroup's [`memory.reclaim`](https://docs.kernel.org/admin-guide/cgroup-v2.html), off the event loop because the write blocks while the kernel pages out. Asking for all of `memory.current` practically always reclaims less than asked, and the kernel then answers `EAGAIN`, so `EAGAIN` is the expected end of a page-out and only other errors are logged as warnings. The recorded pause latency includes the page-out. An unpause is a `compose unpause`; the kernel pages memory back in as the app touches it.

The tier depends on two host mounts that the core's compose file must provide: the host cgroup v2 tree, read-write at `/sys/fs/cgroup`, and `/proc/pressure` at `/host/pressure`. The controller's core-version compose file mounts both (freeshard-controller#246). This repository's own `docker-compose.yml` mounts neither. It maps `PAUSE_ENABLED` only because the controller injects that variable, and #183 left it out of the self-hosting template on purpose. Without them, pressure reads 0.0 and never triggers a demotion, and a pause freezes the stack without paging it out, with one warning per container. `find_cgroup` is shared with Observability's metrics sampler.

### Teardown and the core's stop

`docker_stop_app` and `docker_shutdown_app` both unfreeze the stack first when the daemon reports it paused, because a frozen container can be neither stopped nor removed. A failed unpause (a partly paused stack) is logged and the teardown continues. This unfreeze is deliberately not recorded as a pause-tier transition: the stack is on its way down, not back to `RUNNING`. The allow-lists in the table above are also what keeps the control tick's low-disk stop, which calls `docker_stop_app` on every row the tick reads, off an app that is being reinstalled. That is why #199 passed `force` to the reinstall's teardown and left the lists unwidened. `set_status=False` lets a caller that owns the row's status for the whole of its task, today only the reinstall, change the containers alone; the primitive still announces. `force` exists for the two callers that must tear down whatever the row says: the reinstall and the core's stop.

`get_app_container_state` reduces a stack to one state: `paused` if any container is paused, `running` if all are running, `missing` if there are none, `exited` otherwise. It reports `missing` also when `compose ps` or `docker inspect` fails, so that a probe hiccup degrades a revive into a plain `up` (9f03ca6). A caller cannot take `missing` as proof that the containers are gone. It raises `ComposeFileNotFound` when the app has no compose file.

When the core stops, the lifespan first stops the background tasks, the tick and the installation worker among them, then calls `docker_shutdown_all_apps(force=True)`, and closes the database only after that. Every app with a compose file is taken down, whatever its status, so no app container outlives the core that manages it. The controller relies on this when it upgrades or moves a shard (freeshard-controller#494). A row in a revivable status becomes `DOWN`, which is what it then is, and so a clean restart does not leave `RUNNING` rows for the first tick to count as idle since the epoch. Revives already in flight are not part of the stop: their tasks sit in `app_lifecycle.background_tasks`, which the lifespan never awaits, and the down takes no lock.

The pause, stop and down primitives take no lock either. A revive that races a pause can leave the row at `PAUSED` over running containers; the next revive that passes the throttle finds them running and sets the row back, and that divergence is tolerated. A runtime write that replaces one of Installation's statuses is not tolerated (see above).

### Pause-tier telemetry

`pause_metrics` accumulates only while `telemetry.enabled` is set. It keeps per-app transition counts, the first 1000 pause and the first 1000 unpause latencies, and the first 120 pressure snapshots of a reporting interval. `telemetry.send_telemetry` packages them as the `pause_tier` field and resets them after a successful send; a restart loses them like every other counter. Transitions are recorded as `running_to_paused` for each pause, `paused_to_running` for each real unpause (a revive of a paused stack included), and `<status>_to_stopped` for each stop that writes its status. Cold starts and downs are not counted. The model's docstring, copied from the controller into `data_model/backend/`, describes `pause_tier` as absent from shards with the flag off; a stop records its transition whatever the flag says, and an uninstall's stop records `uninstalling_to_stopped`.

### Image prune

`docker_prune_images` runs `docker image prune -fa`, which removes every image no container references: with an age filter of `apps.pruning.max_age` hours on the `apps.pruning.schedule` cron schedule when `apps.pruning.enabled` is set, and without a filter from `POST /protected/settings/prune-images`. An app in `DOWN` has no containers, so a prune can remove its images and its next revive then pulls them again.

### Boundaries

App runtime owns the transitions among the four revivable statuses, every docker operation on an app's containers, the page-out of a frozen stack, the control tick and its pressure demotion, the pause-tier accumulators, and the image prune. It hosts the manifest reader and the size and version predicates for the rest of shard_core.

It relies on Utilities for `app_compose_command`, which pins every compose call to one app's file and project and never relies on the working directory, and for `throttle`, the signals and `PeriodicTask`, whose catch-all keeps the tick running after a pass raises. It relies on the HTTP surface to send `on_request_to_app` only for admitted requests, the wake path's only trigger. It relies on Installation to create an app's containers with `docker_create_app_containers` while the row is in one of Installation's statuses, to hand the row over by writing `STOPPED`, and to hold the per-app lock across its own teardown. It relies on the composition root to start the tick after the boot-time reconciliation and the profile refresh, and to stop it before taking the apps down. From Observability it reads the disk snapshot's `disk_space_low`. Controller integration's telemetry sender reads and resets the accumulators, and from Controller integration it reads the stored profile for the size predicate (the root's *Deployment mode is explicit* records how that predicate infers the mode). From the host it needs the cgroup v2 tree, PSI and swap.

Of the root invariants it keeps true:

- *Every change to an installed app is announced*: its four write sites (`_mark_running`, `docker_pause_app`, `docker_stop_app`, `docker_shutdown_app`) announce.
- *An app is started only where it can run*: two of the three sites are here.
- *An app's status has one owner*: most of the sites the root lists are here, five gates in `app_tools.py` (one of them the uncalled unpause gate) and three branches in `app_lifecycle.py` (#271).
- *One app's unreadable manifest costs only that app*, for the control tick: currently broken, because one unreadable manifest ends every tick before its demotion (#280).
- *Deployment mode is explicit*, for `size_is_compatible`: currently broken, because the predicate infers the mode from the controller's answer (#270).
- *The auth path does no per-request database work*, for its wake-on-access receiver: currently broken by the profile read.
- *Work that must survive a restart is a row*: by writing only over the revivable statuses, currently broken by the three paths above.
- *The lifespan order is load-bearing*: the tick starts in step 7, after the installation worker, and the apps go down after the background tasks have stopped and before the database closes.

### Constraints

Recorded from the maintainer on 2026-11-09, from decisions taken at triage on 2026-06-29.

**Rejected alternatives.**

- Caching the app status for the revive, reverted in PR #90's review on 2026-05-22.
- Sablier middleware to hold requests while an app cold-starts (#71).
- CRIU checkpoint and restore to remove cold-start latency (#72).

Cold-start latency is addressed by the pause tier (#81) and by reducing apps' idle footprint (#109).


## Routing

Routing decides what Traefik does with every request that reaches the shard. It compiles every router, middleware and service shard_core needs, and the request for the one certificate they share, into a single file built from the routable apps, the default identity's domain and two settings. It rewrites that file at boot and whenever an install, reinstall or uninstall has finished with the app's containers, and it renders the static configuration Traefik starts with.

### Files

`service/traefik_dynamic_config.py` holds `compile_config`, which turns its inputs into the dynamic configuration without touching the database or the disk; it reads `traefik.disable_ssl` and `sundial.enabled` from the settings. `data_model/traefik_dyn_config.py` is the model it fills, generated in 2022 from the Traefik v2 file-provider JSON schema and then patched by hand with `authResponseHeadersRegex` (deddb3d). That patch is why `scripts/generate_traefik_dyn_config_model.py` refuses to run: a regeneration would drop the field the app middleware depends on. `write_traefik_dyn_config` and `NOT_ROUTABLE_STATUS` live in `app_installation/util.py`; the writer gathers the inputs, calls `compile_config` and writes the file. The static configuration is `data/traefik.yml`, or `data/traefik_no_ssl.yml` when SSL is disabled, rendered by `_copy_traefik_static_config` in `app_factory.py`.

### Two configurations, read at different times

```mermaid
flowchart LR
  R[(rows not in<br/>NOT_ROUTABLE_STATUS)] --> W
  M[app_meta.json of each app] --> W
  D[(default identity)] --> W
  B[boot, lifespan step 4] --> W
  I[install or reinstall,<br/>once its containers exist] --> W
  U[uninstall,<br/>once its row is deleted] --> W
  W[write_traefik_dyn_config] -->|apps, domain| C[compile_config]
  S[traefik.disable_ssl<br/>sundial.enabled] --> C
  C -->|model| W
  W -->|truncate, then write| F[core/traefik_dyn/traefik_dyn.yml]
  CA[create_app, on every start] -->|render| ST[core/traefik.yml]
  F -->|file provider, watched| T[Traefik]
  ST -->|read once, when Traefik starts| T
  L[labels on any container] -->|Docker provider, a leftover| T
```

The static configuration holds the entrypoints, the providers, the certificate resolver and the API. shard_core renders it on every process start, in `create_app` before the lifespan runs, to `core/traefik.yml`; its one template variable is `traefik.acme_email`. Traefik reads it once, when Traefik itself starts, from `$XDG_CONFIG_HOME/traefik.yml` ([v2.11 configuration overview](https://doc.traefik.io/traefik/v2.11/getting-started/configuration-overview/)): both compose files, this repository's and every core-version compose of the controller, set `XDG_CONFIG_HOME=/core` and mount the shard's `core/` directory at `/core` in Traefik as well as in shard_core. The dynamic configuration is `core/traefik_dyn/traefik_dyn.yml`, written under `settings().path_root` like everything else shard_core writes. Traefik's file provider watches the directory `/core/traefik_dyn` and reloads on every change. The paths inside the static file are Traefik's own view, as the root invariant *Paths are resolved on the side that uses them* requires.

Both compose files start Traefik only once shard_core reports healthy, which it can do only after the lifespan has finished, so a full start of the stack gives Traefik a freshly rendered static file and a written dynamic file. A restart or recreate of shard_core alone leaves Traefik on the static file it started with. A core upgrade takes the whole stack down and up, so a changed template reaches Traefik then. A change to `traefik.disable_ssl` or `traefik.acme_email` that recreates only shard_core does not reach it. For `disable_ssl` the two files then disagree: the dynamic file moves every router to the entrypoint and TLS setting of the new mode while Traefik still runs the old one, and the shard serves nothing until Traefik restarts.

The dynamic file is the complete routing table: Traefik routes what shard_core writes there and nothing else. The [Docker provider](https://doc.traefik.io/traefik/v2.11/providers/docker/) that the static configuration still enables is a leftover of the label routing that ended in 2022, when the app routers moved into the file (2568cad). It is to be removed together with Traefik's Docker-socket mount, which only the provider uses (root, *Constraints*, decided 2026-11-10, #274). *(Confirmed 2026-11-10 — the code cannot tell a leftover provider from one kept for containers outside this repository.)* No app in the store's history and no core service in any compose file carries a Traefik label. Until the provider is removed, the file is not the complete table: a labelled container on the host can add routers beside the file's, and on a shared host the provider picked up a neighbour's containers (#196).

### Entrypoints and certificates

The static configuration defines three entrypoints: `http` on :80, `https` on :443 and `mqtt` on :8883, the ports the root's Constraints allow Traefik alone to publish. The API's insecure mode opens one more listener, published nowhere but reachable from the `portal` network (root, #198). With SSL, `http` redirects every request to `https` at the entrypoint. Traefik implements that redirect as a router of priority MaxInt−1 ([v2.11 entrypoints](https://doc.traefik.io/traefik/v2.11/routing/entrypoints/)), so no router bound to `http` is ever reached, and every HTTP router binds `https`. The manifest's vocabulary differs from these names: an `entrypoint_port` of `http` means HTTPS on 443, and `mqtt` means MQTT over TLS on 8883.

`http` and `https` carry a `readTimeout` of 300 seconds and no `writeTimeout`, so that connections which never complete a request are reaped while long downloads and server-sent events run on (fd1d05b, #108). The `mqtt` entrypoint is TCP, where these timeouts do not apply.

Every router, HTTP and TCP alike, names the resolver `letsencrypt` and the same `tls.domains`: the shard's domain, with the SAN `*.<domain>`. `tls.domains` takes precedence over a router's Host rule ([v2.11 ACME](https://doc.traefik.io/traefik/v2.11/https/acme/)), so Traefik requests one certificate per shard, covering the domain, every app subdomain and `traefik.<domain>`, and installing an app needs no new certificate. A wildcard can be issued only over the DNS-01 challenge, so the resolver has to use a DNS challenge, as the README explains. Nothing ties the two files together on this point. The certificate and the ACME account live in `core/acme.json`.

The DNS provider is fixed in the template as `azure`, and the template ships inside the image. Traefik v2.11 documents `azure` as deprecated in favour of `azuredns`; the lego bundled with recent v2.11 patches refuses it unless `LEGO_AZURE_BYPASS_DEPRECATION=true` is set, and later patches removed it (#146). This holds the hosted shards off current v2.11 patches, and their compose sets that variable. This repository's compose runs v3.6 and sets neither the variable nor any DNS credentials, so as shipped, with SSL enabled, its resolver obtains no certificate.

### SSL disabled

`traefik.disable_ssl`, which the compose file sets from `DISABLE_SSL` in `.env` and the README reserves for local testing, switches both configurations. The static template becomes `traefik_no_ssl.yml`: `http` and `mqtt` only, with no `https`, no redirect and no resolver. Every HTTP router binds `http` and carries no `tls`. The two templates repeat their shared parts (the providers, the API, the timeouts), so a change to one of those has to be made in both, as fd1d05b did. A TCP router then loses its TLS but keeps its `HostSNI(<app>.<domain>)` rule, and Traefik accepts a host name in `HostSNI` only on a router with TLS ([v2.11 routers](https://doc.traefik.io/traefik/v2.11/routing/routers/)), so in this mode an app's MQTT entrypoint has no route. The same flag decides the scheme of the OIDC issuer and of the shard URL in the welcome log, outside this module.

### Which router serves a request

The file always holds five routers: `shard_core_public`, `shard_core_private` and `shard_core_management` for the three `/core/` prefixes, `traefik` for the dashboard, and the catch-all. Each routed app adds `<app>_http` if it has an HTTP entrypoint and `<app>_mqtt` if it has an MQTT entrypoint, each with a service of the same name. No fixed router or service name ends in `_http` or `_mqtt`, so no app name can collide with them.

| Request | Routers whose rule matches | Served by |
| --- | --- | --- |
| `<domain>/core/public/...`, `/core/protected/...` or `/core/management/...` | that core router, the catch-all | the core router |
| any other path on `<domain>` | the catch-all | the UI |
| `traefik.<domain>/...` | the dashboard router, a core router for `/core/...`, the catch-all | the dashboard |
| `<app>.<domain>/core/...` of a routed app | the app's router, the core router, the catch-all | whichever rule is longer (#191) |
| any other path of a routed app | the app's router, the catch-all | the app |
| any other host, the bare IP and subdomains without a router included | a core router for `/core/...`, the catch-all | shard_core for `/core/...`, the UI otherwise (#230) |

Only the catch-all carries an explicit priority, 1. Every other router has Traefik's default priority, the length of its rule string ([v2.11 routers](https://doc.traefik.io/traefik/v2.11/routing/routers/)). The dashboard's rule is longer than every core router's for any domain of nine characters or more, and longer than the rule an app named `traefik` would get, so such an app is routed but never reached; the name is reserved nowhere else.

The core routers carry no Host matcher, so they answer on every host. For `/core/public` that is load-bearing: the controller's provisioning reads the shard's `whoareyou` at its bare IP address, before the shard's DNS record exists. On an app's host, `<app>.<domain>`, the app's router serves every path: no client calls `/core/...` on an app's host, and both UIs call it on the host they are served from, the shard's domain. The code meets this only through rule length, which holds on `config.toml`'s zone but not on every zone a self-hoster may choose (#191).

An app has one host, so it can have one router of each kind. A manifest that lists two entrypoints of the same kind gets the last one, silently; no store app lists two.

### Middleware chains

The core routers apply `strip` first, which removes `/core/` so the path arrives as `/public/...`, `/protected/...` or `/management/...`, where the HTTP surface mounts its routers. They then apply the admission middleware the root's table lists. An app's HTTP router applies `app-error` and then `auth`.

`auth` asks `/internal/auth` and copies headers back with `authResponseHeadersRegex: ^X-Ptl-.*`. Traefik strips every request header that matches the expression and then copies the matching headers of the auth response onto the request ([v2.11 ForwardAuth](https://doc.traefik.io/traefik/v2.11/middlewares/http/forwardauth/)). So a per-path header in an app's manifest reaches the app only when its name starts with `X-Ptl-`, as every store app's does. Traefik passes the request's host and URI to `/internal/auth` as `X-Forwarded-Host` and `X-Forwarded-Uri`, and the middleware leaves `trustForwardHeader` unset. The HTTP surface takes the app's name from the first label of that host, the label the rule `Host(<app>.<domain>)` matched. A browser sends the host in lower case while the router's host and the app's row keep the name as written, so an app whose name contains a capital letter, which the zip validation allows, cannot be reached.

`app-error` hands every response with a status in 500–599, or 401, to shard_core's `/internal/app_error/{status}`, which renders the splash. Traefik forwards the client's Host header to it by default ([v2.11 ErrorPages](https://doc.traefik.io/traefik/v2.11/middlewares/http/errorpages/)), which is how the splash knows which app it is for. Because `app-error` comes before `auth`, it also covers the forwardAuth's own 401 and turns it into the "Access Denied" page. Since 8f9b4c3 (#235) all other client errors reach the browser as the app sent them. An app's own 401 is still replaced, and #236 proposes deciding by the client's `Accept` header instead.

No router forwards to shard_core outside the three `/core/` prefixes. The only requests that reach `/internal` through Traefik are those Traefik makes itself: the three forwardAuth checks and the error page. This is what keeps `/internal` unrouted (root, *Admission is decided at the proxy*).

### MQTT

An MQTT entrypoint becomes a TCP router on the `mqtt` entrypoint, matching the SNI `<app>.<domain>`. Traefik terminates TLS with the shard's certificate and opens a plain TCP connection to `<container_name>:<container_port>`, which is 1883 for the store's mosquitto. This TCP router carries no middleware, so the connection is admitted without asking shard_core. It never reaches `/internal/auth` either, so MQTT traffic neither wakes a stopped app nor counts as an access on the control tick's idle clock. An app whose clients arrive only over MQTT is therefore reachable only if its manifest declares `always_on`. The store's authoring guide asks this of messaging apps, mosquitto declares it, and nothing in shard_core checks it. When no routed app has an MQTT entrypoint, the TCP section is left out of the file, because, as the code records, Traefik cannot handle the empty objects (d36ba31).

### The root UI

The catch-all is named `web-terminal` whatever it serves: `PathPrefix(/)` at priority 1, pointed at the `sundial` service when `sundial.enabled` is set and at `web-terminal` otherwise. Both services are always defined, the unused one referenced by no router, and only the tests read the router's name. Sundial replaces web-terminal at the root and is not mounted beside it (see Constraints); it serves at `/` natively, so the swap needs no prefix stripping (PR #244). Settings are read once per process, so the switch takes effect at the boot that follows the change, whose rewrite carries it. Both UIs call the API at `/core/...` on the host they are served from and open an app at `<app>.<location.host>`, which is the app's host only when the UI is served from the shard's domain.

### When the file is rewritten

`write_traefik_dyn_config` reads every row whose status is not in `NOT_ROUTABLE_STATUS` (`INSTALLATION_QUEUED`, `ERROR`, `UNINSTALLATION_QUEUED`, `UNINSTALLING`) and loads each one's manifest. A manifest it cannot load is skipped with a warning, so that one broken row cannot stop the boot (155ee52, #158). It then reads the default identity, compiles, and writes the whole file. It has three callers. The lifespan calls it at step 4, after the reconciliation of interrupted installs and uninstalls (root, *The lifespan order is load-bearing*). The worker calls it at the end of `_install_app_from_zip`, once the app's containers exist (4c94e5e moved it after their creation), which every store install, zip install and reinstall passes through. And `_uninstall_app` calls it after deleting the row and before announcing the change. The boot's write completes before the worker starts, and the worker runs one task at a time, so two writes never overlap.

The routed set is therefore a snapshot taken at the last write. No status write rewrites the file, and `/internal/auth` admits a request without looking at the app's status, so `NOT_ROUTABLE_STATUS` takes effect only at the next write; #200 (its fourth item) proposes rewriting on every `on_apps_update`. `INSTALLING` and `REINSTALLING` stay routable because the install writes the file while the row holds them, and the row then becomes `STOPPED` without another write. An app being uninstalled keeps its router until its row is gone, unless a write from an earlier task in the queue, or a boot, drops it first. A reinstall that fails leaves its app routed in `ERROR` until the next write, which may come from an unrelated install. A clean stop's `DOWN` over an `ERROR` row (root, *An app's status has one owner*) gets the app routed again at the next boot, provided its manifest is still readable.

The domain is read at every write as well, and nothing writes when it changes. `POST /protected/identities/{id}/make-default` changes the default identity and announces `on_identity_update`, which the routing does not receive. The routers keep naming the old domain until the next write, which then moves every router, and the certificate request, to the new one. The settings change only with a restart, which the boot's write covers.

Traefik applies a write when its file provider is notified of it. After each reload it waits two seconds by default before taking further changes, and keeps only the latest of those ([v2.11 providers](https://doc.traefik.io/traefik/v2.11/providers/overview/)). The install sets `STOPPED` and announces it right after its write, so a client that opens the app straight away can reach the catch-all before the app's router exists (#230). The write itself truncates the file and then fills it in two writes (#228). A reload that lands in between sees no routers at all, shard_core's own included. A write that fails part-way leaves only a fragment of the file, and the previous configuration is lost.

### Boundaries

Routing owns the dynamic file and everything in it: the routers and their precedence, the middleware chains, the services and the certificate request. It also owns the routability filter and the static templates with their render. It keeps no state between writes; every write recomputes the whole file from its inputs.

It relies on Installation to call the writer once an app's containers exist and once a row has been deleted, and on the composition root to call it at step 4 and to run `create_app` before the lifespan. It reads manifests through App runtime's `get_app_metadata` and the domain through Identity's default identity and the `dns` settings. It relies on the HTTP surface for the four `/internal` endpoints its middlewares name, and for mounting the HTTP surface's routers at the paths `strip` leaves. From the compose files it needs the container names `shard_core`, `web-terminal` and `sundial` on the `portal` network, `core/` mounted at `/core` in both Traefik and shard_core, `XDG_CONFIG_HOME=/core`, Traefik starting after shard_core is healthy, the three published ports, and the DNS provider's credentials. From each app it needs a `container_name` on `portal` for every entrypoint, a name in lower case, per-path headers named `X-Ptl-*`, at most one entrypoint of each kind, and `always_on` if the app is reached only over MQTT. From the controller it needs the DNS record for the domain and a Traefik that still accepts `azure`.

Of the root invariants it keeps true:

- *Admission is decided at the proxy*: it compiles every router shard_core has, every HTTP app router carries `auth`, and `/internal` is reached through Traefik only by Traefik's own checks and the error page. Until the leftover Docker provider is removed, a labelled container can add routers beside these.
- *Un-pairing takes effect on the next request*: the dashboard sits behind `auth-private`.
- *An app's status has one owner*: `NOT_ROUTABLE_STATUS` is one of its sites, and it takes effect only when the file is written.
- *Paths are resolved on the side that uses them*: the static file's paths are Traefik's, the writer's are shard_core's.
- *The lifespan order is load-bearing*: the boot's write follows the reconciliation, and the static file is rendered before the lifespan begins.
- The Traefik v2/v3 constraint: the dynamic file loads under both, with the dashboard's `HostRegexp` as the one rule v3 reads differently. The static file's `azure` provider holds the hosted shards off current v2.11 patches and keeps this repository's v3.6 compose from obtaining a certificate.

### Constraints

From the written record, each decided by the maintainer:

- The root UI is switched between web-terminal and Sundial by a configuration override from the controller, and is never served at a path of its own (PR #171).
- shard_core does not proxy app traffic to enrich the splash page with the app's own response (PR #92, for #91).
- `data_model/traefik_dyn_config.py` is never regenerated from the schema, because the model was patched by hand (deddb3d).

## Identity and signing

Identity and signing owns the shard's RSA identities and their avatar images, derives the shard's ID and domain from the default identity, and signs every call to the controller and every `/internal/call_peer` request with it. What the rest of shard_core and every counterparty build on is that the shard's ID is the hash of its public key: the ID names the shard and authenticates it at once, so the key cannot change without the shard becoming another shard.

### Files

`identity.py` creates the default identity on first boot, reads it, updates an identity's name and description, switches the default, and seeds the default identity's name from the controller's profile when a pairing leaves one terminal. `crypto.py` wraps the `cryptography` package for RSA-4096 key generation, PEM serialization and the hash ID, and `human_encoding.py` turns the hash into characters; its `decode` has no caller outside the tests. Both were copied from the `common_py` library when shard_core dropped that dependency (433d371). The copy brought along a raw RSA-PSS sign and verify pair over SHA-256 and two AES-OFB helpers, which nothing outside the tests has ever called. `signed_call.py` signs outgoing HTTP requests. `assets.py` is a file store under `core/assets/`, and `avatar.py` finds an identity's avatar in it. `data_model/identity.py` holds four models: `Identity`, the stored row plus the computed `short_id`, `public_key_pem` and `domain`; `OutputIdentity`, what HTTP responses carry; `SafeIdentity`, what app templates see; and `InputIdentity`, the body of `PUT /protected/identities`. The routes that expose all of this, `web/protected/identities.py` and `web/public/meta.py`, belong to the HTTP surface.

### The shard ID

```mermaid
flowchart LR
  K["private key, RSA-4096<br/>identities.private_key"] --> P["public key<br/>PEM SubjectPublicKeyInfo"]
  P -->|SHA-512| H["512-bit digest"]
  H -->|"human encoding<br/>5 bits per character"| I["shard ID, 103 characters<br/>identities.id"]
  I -->|"first 6 characters"| S["short ID"]
  I -->|"first dns.prefix_length characters<br/>lowercased, under dns.zone"| D["domain"]
```

The ID is computed once, when `Identity.create` generates the key, and stored as the row's primary key; nothing on the shard recomputes its own ID from the key afterwards. The encoding maps every 5 bits to one of 32 characters, `abcdefghjklnpqrstvwxyz0123456789`, and pads the last group with zero bits, so a 512-bit digest becomes 103 characters, all lowercase.

The ID is a self-certifying name (root, *Pattern glossary*).

The derivation is a wire contract. The controller recomputes IDs with its own copy of the library that `crypto.py` and `human_encoding.py` were copied from, so the hash, the PEM serialization of the public key and the alphabet must stay as they are on both sides. A change to any of them breaks every recomputation of an ID: a new shard would fail the controller's check, and every existing peer key would be rejected. The stored ID itself is never recomputed. Nothing checks the two copies against each other, and the tests derive IDs only from freshly generated keys, so they would pass after such a change. The copies are kept in step by hand: both repositories pin `bitstring<5`, because bitstring 5 removed the `BitArray(bytes=...)` form that `human_encoding.encode` uses (6eb1ef8). The alphabet is module state, set by `init()` when the module is imported; calling `init()` again replaces it for the whole process, which only the tests do.

### The short ID and the domain

The short ID, the ID's first 6 characters, is the shard's name outside the shard. It is the key ID of every signature the shard makes, the prefix under which the controller and peers look the shard up, the DNS label the controller creates for a hosted shard, `portal.short_id` in app templates, and what people exchange to peer. The controller keeps it unique among the shards it manages (freeshard-controller#350).

The domain is not stored on the shard. `Identity.domain` computes it from the settings on every access: the ID's first `dns.prefix_length` characters, lowercased (a no-op for this alphabet), under `dns.zone`. A change of zone therefore takes effect at the next boot without touching a stored row. On a hosted shard the controller creates the DNS record from the first 6 characters whatever `prefix_length` says, and its uniqueness check mirrors that default, so `prefix_length` must stay 6 there; nothing sets it to anything else. Peers and both UIs address another shard as `https://<short ID>.freeshard.cloud` regardless of either setting (`peer.update_peer_meta`), and `call_peer` relays to `https://<app>.<id>.freeshard.cloud/<rest>` with the ID the caller passes. That holds for hosted shards only; the owner of a self-hosted shard would have to hand out its address (#167).

Every consumer of the default identity reads it at its own time:

| Consumer | Reads the default identity | Sees a change |
| --- | --- | --- |
| `whoareyou`, `GET /protected/identities/default`, `signed_request` | On every request or call | At once |
| The cookie domain a pairing sets | On every pairing | At once |
| `portal` in the per-path header templates of `/internal/auth` | Through `_identity_cache` | At the next `on_identity_update` |
| The Traefik dynamic config: app routes, dashboard rule, certificate domains | On every write: boot, install, reinstall, uninstall | At the next write |
| `portal` in compose templates and OIDC redirect URIs | On every render: every app at boot, one app at its install or reinstall | At the next render |
| The OIDC provider's issuer | Once per process, at the first OIDC request | At the next restart |
| The owner user's display name | Once, when the owner row is created | Never |

Outside the boot-time database paths, `on_identity_update` follows every write that can change the default identity's row (`init_default_identity`, `make_default`, `update_identity`), and its one receiver drops `_identity_cache`. That keeps the auth path's identity lookup out of the database (root, *The auth path does no per-request database work*). Nothing else reacts to the signal, which is sound only because the key does not change.

### One identity for the life of the shard

`init_default_identity` creates the first identity, flagged default, when the `identities` table is empty, and returns the default otherwise. It runs after the snapshot restore and the TinyDB import, so a restored shard keeps its key, ID and domain (root, *A backup restores the shard as it was*). Exactly one row is flagged default. The schema does not enforce this: `is_default` has no unique index, `get_default` returns whichever flagged row Postgres yields first, and a table without a flagged row makes every reader of the default identity raise, the boot included. Every reader also needs the default row to load as an `Identity`, and today the identity update does not guarantee that. The code keeps the single flag: the first identity is created flagged, and `make_default` clears one flag and sets the other in a single transaction.

The shard's key and its ID are fixed for the shard's life, and its domain follows from the ID and the zone setting (see Constraints). The counterparties are built on it. The controller binds the key to the full ID and checks it when a shard moves (freeshard-controller#345, #480). Peers pin a peer's key to its full ID after first contact; today the peer binding compares only the typed prefix, usually the short ID, which the Peers section records as a violation of that decision (see Peers).

Two operations contradict this. `PUT /protected/identities` without an `id` creates a further identity with its own key, and `POST /protected/identities/{id}/make-default` makes it the default. A further identity has no function: nothing signs with it, since `signed_request`'s `identity` parameter has had no caller since it was added (ff9d825); nothing publishes it; and neither web-terminal nor Sundial creates, lists or switches identities. A switch cuts the shard off from everything above. The controller knows no shard under the new short ID and answers every signed call with 401, so the next profile refresh stores no profile, which the size gate reads as admitting every app (root, *Deployment mode is explicit*). `whoareyou` changes at once, and new pairings set their cookie for a domain the browser is not on. On a hosted shard the app routes and the certificate move at the next Traefik write to a name with no DNS record, and the templates and the OIDC issuer follow at the next boot.

### What is public and what is secret

An identity is the shard's public profile. `GET /public/meta/whoareyou` publishes the default identity without authentication as an `OutputIdentity`: ID, name, description, `is_default`, public key and domain. The Public page of both UIs warns that name and description are public, and migration 0005 dropped the identity's email column because a personal address has no place there (see Constraints). The controller, peers and both UIs read the endpoint: a peer parses the whole `OutputIdentity` on every refresh, and the UIs read it to show the shard and to notice that it is back after a restart. Its fields are therefore an interface. The default identity's avatar is public as well, at `GET /public/meta/avatar`.

The private key leaves the `identities` table in two directions only: into `signed_request`, and into `core/db_snapshot.json`, which the backup writes before each run, keeps on disk between runs and carries off the shard encrypted. Both hold it in the clear, as the shard holds most of its secrets; the owner's email confirmation token and the OIDC codes and tokens are stored only as digests. #211 discusses that posture for the OIDC signing key, and why the AES-OFB helpers in `crypto.py`, an unauthenticated mode, are no answer to it. What keeps the key out of HTTP responses is the response model alone. Every route that returns an `Identity` declares `OutputIdentity`, and FastAPI drops the fields that model lacks; a route that returned an `Identity` without one would publish `private_key`.

Apps see the default identity as a `SafeIdentity`, rendered as `portal` into compose templates, per-path header templates and OIDC redirect URIs, and carrying no private key (0fc7cac). Its four fields, `portal.domain`, `portal.id`, `portal.short_id` and `portal.public_key_pem`, are documented for app developers ([docker-compose template](https://docs.freeshard.net/developer_docs/docker_compose_template/)), so renaming or dropping one breaks published apps. All four are public, so none of them is a secret; per-app secrets come from the templates' `secret()` function (#138).

### Signing

`signed_request` is `requests.request` with a signing hook, run in a worker thread. On every call it reads the default identity from the database, and the hook signs with [HTTP Message Signatures](https://www.rfc-editor.org/rfc/rfc9421.html#section-3.3.1) as `rsa-pss-sha512`, with the short ID as key ID. A signature covers the method, the authority, the target URI including its query, the `Date` header and, for a request with a body, a SHA-256 `Content-Digest` of it; `Content-Type` is not covered. It carries a `created` time and no nonce or expiry. A verifier must reject a replayed signature and one older than the call needs; neither the controller's (freeshard-controller#519) nor `peer.verify_peer_auth` does today. The request is sent with `stream=True`, which `/internal/call_backend` and `/internal/call_peer` need to pass the answer through as it arrives (5359ad2, #38), and with no timeout, so the caller waits as long as the counterparty holds the connection (root, *The lifespan order is load-bearing*). Callers catch the exception types of `requests`, so the HTTP client is part of the interface.

The authority a shard's signature carries, and how far shard_core may lend it, are set out in the root's *The controller is one signed counterparty*. App usage reports, which still go to the old backend (#208), are signed too. Of the exchanges with the controller and peers, the one without a signature is the peer-key refresh.

### The owner's name from the profile

`enrich_identity_from_profile` receives `async_on_first_terminal_add`, which the pairing route sends when a pairing leaves exactly one terminal. It refreshes the profile and, when the profile names an owner, sets the default identity's name to it, which seeds the shard's public profile with the name the controller recorded when it assigned the shard (798d758, "enrich default identity from profile during first pair"). The seed belongs to the shard's first pairing; afterwards the name is the owner's to edit on the Public page. The code meets this only at the first pairing. The signal fires again whenever every device has been removed and one is paired again, and the name is then reset to the controller's record over whatever the owner set. The same handler writes the owner's candidate address; People and owner email specifies that transition. What the handler does when the profile refresh fails is in that section too.

### Avatars

An identity has at most one avatar, the file `core/assets/avatars/<ID>.<extension>`, which lies under `core/` and so travels with the backup. `find_avatar_file` finds it by the ID; more than one file for an identity is logged and treated as none. An upload replaces the identity's previous avatar whatever that one's extension. Avatars are served from the shard's own origin: the default identity's to anyone at `/public/meta/avatar`, any identity's to a terminal at `/protected/identities/{id}/avatar`. So an avatar operation touches only the file of the identity it names, and an avatar is inert image data. The upload does not guarantee either today.

### Boundaries

Identity and signing owns the `identities` rows and the key material in them, the ID derivation and its codec, the signature on every request the shard sends as itself, the four identity models, and the avatar files.

It relies on Database for the `identities` table and for one transaction per `db_conn()` block, committed when the block exits. Others reach the table past this module: the HTTP surface inserts new identities itself (`put_identity`), and five sites read the default identity from `database/identities` directly, bypassing `get_default_identity`: the auth handler, the pairing route, the owner bootstrap, and the template render and the Traefik write in `app_installation/util.py` (root, Unresolved forks, *Layering*). It relies on the HTTP surface to declare `OutputIdentity` on every route that returns an identity, and on Backup for the only off-shard copy of the key. From Controller integration it uses `refresh_profile` and the profile's owner fields. The pairing route sends the signal the enrichment receives, and Terminals and pairing mints terminal IDs with `human_encoding.random_string`, which draws from the non-cryptographic `random` module (#253). People and owner email receives the pending email the enrichment seeds; its owner row took its display name from the default identity once, when the row was created, and the two names are independent after that. The controller, peers and both UIs read `whoareyou`. The controller and Peers recompute IDs, Peers with this module's code and the controller with the library it was copied from.

Of the root invariants it keeps true:

- *The auth path does no per-request database work*, for the identity lookup: every write to the default identity's row sends `on_identity_update`, the only invalidation of `_identity_cache`.
- *A backup restores the shard as it was*: the first identity is generated only on an empty table, after the restore.
- *The controller is one signed counterparty*: every request the shard sends as itself carries the default identity's signature and short ID.
- *The lifespan order is load-bearing*: the default identity exists before the owner user, the Traefik config and the compose templates, which are all built from it.

### Constraints

From the written record:

- Shard keys are never rotated, so a shard's key and ID are fixed for its life, and its domain follows from the ID and the zone setting (the maintainer ruling recorded in freeshard-controller#345, 2026-07-04).
- No personal address goes on an identity, because `whoareyou` publishes it (migration 0005, #220).

## People and owner email

People and owner email owns the people on the shard, today only its owner, and the owner's address as it moves from unverified candidate to verified address. It is also the only shard code that writes the controller's copy of that address, `shards.owner_email`, on its own behalf, and that copy is the one the controller mails. Two other writers touch the shard's copy: `identity.enrich_identity_from_profile` seeds the candidate from the controller's profile, and the boot-time database paths seed or demote it.

### Files

`service/user.py` holds `ensure_owner_user`, the lifespan step that creates the owner on a fresh shard. `service/owner_email.py` holds every runtime transition of the address but one, the first-pairing seed in `identity.py`. It also holds the confirmation token, the send budget, and the module's three calls into `freeshard_controller.py`: `send_verification_email`, `relay_email_to_owner` and `set_owner_email`. `data_model/user.py` holds `User`, the row; `OutputUser`, which carries the candidate and never the token; `InputUser`, the validation of what a client may write; and `Role`.

Two of the module's guarantees live in the SQL of `database/users.py`: `claim_email_token` spends a token in one conditional `UPDATE`, and `promote_pending_email` promotes only the candidate the token was spent on. The routes, `/protected/users/me` with its two sub-routes and `/public/users/confirm-email`, belong to the HTTP surface; this section records what the module needs from them.

### The people on the shard

The `users` table holds the shard's people. Today it holds exactly one, the owner, with role `owner` and username `owner`. Members are planned for the later phases of #141, and no code creates one. At most one owner can exist, because every path that creates one inserts the username `owner`, which is `UNIQUE`; `db_users.get_owner` selects by role.

The owner exists before any terminal can be paired, because pairing binds the new terminal to it and `web/public/pair.py` uses the owner row without checking for it. Each boot path creates it at a different point. On a fresh shard it is `ensure_owner_user`, which the lifespan runs right after the default identity (root, *The lifespan order is load-bearing*, step 2). On a shard upgraded to 0.42 it is migration 0002, which creates it from the default identity and binds every existing terminal to it. On a shard still holding its pre-Postgres data it is the TinyDB import's `_ensure_owner_user`, which #225 judges unreachable. On a restored shard it is the snapshot's own row; a snapshot written by 0.40.1 to 0.41.3 carries none, and one that holds a terminal fails to restore before anything could create one (see *Seeding from outside the module*).

Every terminal belongs to a user (`terminals.user_id` is `NOT NULL`), and the person behind a request is resolved through its terminal: `/protected/users/me` and the OIDC provider both read the terminal's `user_id`. Every pairing binds to the owner, so every terminal is the owner's.

A user's `id` is its OIDC subject: `sub` is the id as a string. It is a database counter and deliberately not derived from the shard's identity hash, because the shard and its owner are separate things (the maintainer's review of #147). Apps link their accounts to that `sub`, so the id must survive a restore, and it does: the snapshot restore inserts users with their ids and advances the sequence past them.

The owner's `display_name` is copied from the default identity's name when the row is created and is changed afterwards only through `PATCH /protected/users/me`; nothing keeps it in step with the identity. The OIDC provider emits it as the `name` claim. On a shard upgraded to 0.42 the copy is the name the identity held at the upgrade, set from the controller's profile at its first pairing or edited since on the public page. On a fresh shard the row is created before any pairing, so the copy is the identity's placeholder, `Shard Owner`, and the first pairing renames the identity but not the user. That placeholder is needed, because the controller usually does not know the owner's name at that point. A name the owner sets reaches every app automatically, and no app keeps the placeholder. *(Confirmed 2026-11-10 — the code cannot show whether the placeholder is meant to reach apps.)* How an app receives the name is the OIDC provider's design. Today nothing carries a rename to apps: the provider reports the current name only in the tokens and userinfo answers it issues afterwards, so an app that took the placeholder at its first login keeps it unless it asks again, and web-terminal has no control to rename the owner at all. Sundial edits the name and tells the owner it is separate from the public page's.

`disabled` and `password_hash` have no writer. They are scaffolding for the login page and the members of #141's later phases, and `password_hash` is not on the model at all. `disabled` is read in two places: every `/protected/users/me` route refuses a disabled user with 403, and the OIDC provider treats one as absent. Terminal admission does not consult it, so a disabled user's terminal would still pass every other `/protected` route. `Role` mirrors the Postgres enum `user_role` by hand, as the comments on both sides say.

### The owner's address

The address lives in two columns of the owner's row. `users.email` is the verified address. It holds only an address that somebody proved they can read by opening a link delivered to it, with one exception: with `email.enabled` off, the address the owner types is stored as typed. `users.pending_email` is the unverified candidate, at most one per user, and a new candidate replaces the old one. There is no verified flag; the column an address sits in is its state.

That invariant is what makes the OIDC provider's claim true. The provider emits `email` with `email_verified: true` for whatever `users.email` holds, and with nothing there it emits neither claim; there is no synthetic fallback. With mail off it therefore asserts verification for an address nobody confirmed, which #220 accepts because the owner controls the machine.

The owner always has a verified address. A new address replaces it only once the new one is verified, and only then is the old one cleared, on the shard and in the controller's copy. A verified address is never removed outright, and an unverified one never stands in for it. With mail off an address is taken as typed (see *Constraints*), so there a new address replaces the old one at once. *(Confirmed 2026-11-09 — the code implements the clear that #220 permitted, so it cannot vouch for the rule that supersedes it.)*

The code does not meet this rule yet. `ensure_owner_user` creates the owner of a fresh shard without an address, and the TinyDB import creates it with at most a candidate. Migration 0005 and the first pairing leave a hosted shard with no verified address and only a candidate: 0005 emptied `users.email` and moved the identity's unconfirmed address into the candidate, and the first pairing seeds the controller's address as one. And `clear_email`, the clear row below, removes a verified address outright, which #220 permitted and the rule supersedes. With only a candidate on file it also nulls the controller's copy, after one warning, and every mail about the shard stops (see *The controller's copy*).

Every write to the address, by operation:

| Operation | Code | `users.email` | Candidate | Token | Controller calls |
| --- | --- | --- | --- | --- | --- |
| Set, mail on | `set_email` | kept | the address | new | verification mail to the address |
| Set, mail off | `set_email` | the address | cleared | cleared | mirror of the address |
| Resend | `resend_verification` | kept | kept | new | verification mail to the candidate |
| Discard | `discard_pending` | kept | cleared | cleared | none |
| Clear | `clear_email` | cleared | cleared | cleared | warning relay with mail on, then mirror of null; no call and no write when neither address is on file |
| Confirm | `confirm_email` | the candidate | cleared | spent | warning relay, mirror, and a confirmation relay if the mirror was accepted |
| Pairing that leaves one terminal, no verified address | `identity.enrich_identity_from_profile` | kept | the profile's address | cleared | profile refresh |
| Upgrade to 0.42 | migrations 0002 and 0005 | emptied | the identity's address | none | none |
| Restore of a pre-0005 snapshot | `db_snapshot._demote_unverified_owner_email` | emptied | the default identity's address | untouched | none |
| TinyDB import | `tinydb_migration._ensure_owner_user` | empty | the TinyDB identity's address | none | none |

Outside `owner_email.py`, only the boot-time paths write `users.email`. Migration 0002 copied the identity's unverified address into it, and 0005 empties it again in the same upgrade, since both first shipped in 0.42.0. A restore writes back what a snapshot written by 0.42.0 or later holds. Every other path leaves it empty.

### The confirmation token

The shard mints the token with `secrets.token_urlsafe(32)`, 256 random bits, and stores only its SHA-256 digest, with an expiry one hour out. The two token columns are written together, and a `CHECK` constraint enforces that. The controller is asked only to deliver the token. It builds the link from the shard domain it already knows, `https://<shard domain>/?confirm_email=<token>`, so no URL the shard supplies is ever rendered into a mail. Where Sundial is the shard's UI, the link opens its confirmation view, which posts the token to `POST /public/users/confirm-email` when the owner clicks. There is no `GET`, because mail scanners and link prefetchers follow links and would spend a single-use token before the owner does. The route is unauthenticated on purpose: the token proves possession of the mailbox, which is the fact being verified.

`_claim_token` compares the digest with every stored one using `secrets.compare_digest`, then spends the match in one conditional `UPDATE` that also requires an unexpired token and a candidate on file, and returns the row. The spend comes before anything else, so a double-clicked link promotes once and the mails and controller calls that follow cannot be replayed. The route answers 204 to every well-formed token, matched or not, so it cannot be used to learn whether a candidate is pending. It counts only misses toward its limit of 20 a minute, so a flood of guesses earns a 429 but can never stop the owner's own link from working.

A confirmation promotes the address its own link was mailed to, or nothing. A token is bound to whatever candidate is on file when its link is opened: the claim returns the current candidate and the promotion takes that one. Every writer of `pending_email` retires the token whenever it replaces the candidate, which agents.md states as a rule. `set_email` writes candidate and token together. `discard_pending`, `clear_email` and the mail-off `set_email` clear both. The first-pairing seed clears the token (75bad37). The boot-time paths act only on data shapes that carry no token. The resend path does not keep the guarantee today.

### Confirmation

```mermaid
sequenceDiagram
    participant UI as Sundial
    participant S as owner_email
    participant DB as users row
    participant C as Controller
    UI->>S: POST /public/users/confirm-email with the token
    S->>DB: spend the token and read the candidate, in one conditional UPDATE
    S->>C: relay the change warning, which reaches the controller's copy
    S->>DB: promote the candidate if it is still the one the token was spent on
    S->>C: mirror the promoted address
    opt the mirror was accepted
        S->>C: relay the confirmation, which now reaches the new address
    end
    S-->>UI: 204, whether or not anything was promoted
```

The old address is warned before the switch is mirrored, because the controller's relay only ever mails the address the controller holds; sent after the mirror, the warning would reach the new address. The promotion is guarded on the candidate the token was spent on, so a candidate set while the link was in flight survives. The confirmation then promotes nothing, after the warning has already gone out. When the mirror is refused or fails, the confirmation stands and the confirmation mail is skipped, since the relay would deliver it to the abandoned address.

Delivery to the controller is owed. When a mirror or a change notice fails, the shard retries it, or reconciles with the controller's copy when it next refreshes the profile. A retried or reconciled mirror goes out within the window in which the controller still accepts the address, and after that window only once the shard has verified the address again (freeshard-controller#435). *(Confirmed 2026-11-10 — the code's best-effort calls cannot tell a loss accepted by design from a missing retry.)* Today both are logged and dropped. After a failed mirror the controller keeps mailing the old address, which the warning has just told it receives its last message, and Sundial treats saving the address already on file as a no-op, so the owner cannot send it again. Because the warning must precede the mirror, a warning dropped before a mirror that succeeds can no longer reach the old address at all.

### The controller's copy

The controller keeps its own copy of the owner's address, `shards.owner_email`, and every mail about the shard goes to that copy, except the verification link: each relay the shard requests, and the storage warnings, billing notices and wind-down mail that #220 lists. When the copy is empty, the relay refuses and those mails stop.

The shard writes that copy on three events and no others. A confirmation mirrors the promoted address, a set with mail off mirrors the typed address, and a clear mirrors null. A set with mail on does not touch it, and neither do the boot-time paths, migration 0005 included. The controller refuses an address it has not itself sent a verification link to for this shard (freeshard-controller#435), so a set with mail off, which sends no link, cannot change the controller's copy. A self-hosted shard is unknown to the controller, so there every mirror fails and is logged as an error.

The rules in *The owner's address* and *Confirmation* make the controller's copy follow the verified address: the shard replaces it when a new address is verified, never clears it outright, and owes the controller every change. The code diverges from this on every hosted shard that migration 0005 or the first pairing left with only a candidate: the shard holds no verified address, while the controller still holds the address the owner signed up with and keeps mailing it. `clear_email` does nothing when the shard holds neither a verified address nor a candidate, so that a redundant clear cannot mirror a null over the signup address and silence every mail to a paying customer (75bad37).

### The mail switch

`email.enabled`, on by default, declares whether the shard can send mail at all. It is named for that capability and deliberately not for the deployment, because a hosted shard may switch mail off and a self-hosted one may gain its own (5101509). It is never inferred from a failed delivery, which during a controller outage would silently downgrade a security control (#220). `set_email`, `resend_verification` and the warning in `clear_email` read it, and `GET /protected/settings` publishes it as `email_enabled` so that a UI offers a resend only where a link can be sent (#223).

With mail off, `set_email` stores the address as typed and drops any candidate, `resend_verification` refuses, and a clear sends no warning. A candidate written by one of the seeding paths can then never be confirmed, and Sundial tells the owner to discard it and type the address again. This repository's `docker-compose.yml` maps no variable for the switch and mounts no `local_config.toml`, which the image excludes, so a shard started from it runs with mail on, where every send fails, unless the operator adds the variable by hand.

### Sending limits

Every verification mail costs the controller a real send, so `owner_email` rations them with one budget shared by both routes and the whole process, five per rolling hour (`_send_limit`); a shard has one owner, so a budget per client would only hand an attacker a fresh one per source address. The budget is charged before anything is written, so that a refused request cannot replace the token of a link already in the owner's inbox, and only where a send is attempted, so a shard with mail off is not rationed.

The controller may refuse a send the shard's budget admits (freeshard-controller#435). By then the shard has already replaced the token, so the owner's earlier link stops working, and both routes report the refusal as a failed delivery, with a 502. The warning and confirmation relays are not rationed by the shard. Both shard-side counters, this budget and the confirm route's miss counter, live in the process and start empty after a restart (root, *Work that must survive a restart is a row*).

### What a client may write

`InputUser` takes `display_name`, at most 200 characters and never null, and `email`, at most 254. An explicit `null` takes the clearing path, which the rule in *The owner's address* does not allow, and an omitted field leaves the address alone; the route tells the two apart with `exclude_unset`. An empty string is rejected, so a form that blanks its field cannot take the clearing path by accident. An address is checked with `email_validator`, without a deliverability lookup, which would block the event loop on DNS and prove less than the confirmation mail does, and without SMTPUTF8. The normalized form is what is stored, because it is what the OIDC provider asserts to third parties.

### Only the owner's address

Everything `owner_email` does is owner-global: the relay mails the controller's owner address and the mirror rewrites it. The address routes therefore refuse any user whose role is not `owner` with 403, and the service relies on that check and acts on whatever user it is handed. `_claim_token` matches tokens across all users, which is safe only because no one but the owner can obtain one. Giving members an address (#141) first needs the owner-global calls separated from the per-user columns, and #220 records that a self-hosted shard has no way to verify a member's address at all.

### Seeding from outside the module

`identity.enrich_identity_from_profile` receives `async_on_first_terminal_add`, which pairing sends whenever a pairing leaves exactly one terminal, and the pairing request awaits it. It refreshes the profile from the controller and, while the owner has no verified address, writes the profile's address as the candidate and retires any token, which leaves the shard with only a candidate (see *The owner's address*). It replaces whatever candidate is on file, the owner's own included; 75bad37 made it retire the token together with the candidate it replaces. A controller that cannot be reached fails that pairing (root, *Deployment mode is explicit*, and #194).

The snapshot restore applies the rule of migration 0005 to a snapshot whose identity rows still carry an address, in `_demote_unverified_owner_email`, which #224 means to retire. That rule can act only on a snapshot that carries a `users` table, and no release before 0.42.0 wrote one. A snapshot written by 0.40.1 to 0.41.3 has terminal rows without `user_id`, which 0002 made `NOT NULL`, and the restore inserts them as they are. On any such snapshot that holds a terminal, the whole restore rolls back and the boot fails, and it fails again on every restart, because the database stays empty. The TinyDB import seeds the candidate the same way and binds the terminals it imports to the owner it creates (0beeb89).

These paths leave in `users.email` only what a snapshot written by 0.42.0 or later already held there, never leave a token beside a candidate it was not minted for, and never write the controller's copy.

### Boundaries

People and owner email owns the users table's meaning, the two address columns and their transitions, the confirmation token and the send budget, and it is the only shard code that writes the controller's copy of the address on its own behalf. It hosts `ensure_owner_user` for the lifespan.

It relies on the pairing route, `web/public/pair.py`, to bind every new terminal to the owner and to send `async_on_first_terminal_add` when a pairing leaves one terminal, and on Terminals and pairing to resolve a request's terminal from its cookie. It relies on the HTTP surface to refuse a non-owner on the address routes, to answer the confirm route identically whether or not a token matched, to count only misses there, to offer no `GET` confirmation, and to publish `email_enabled`; the address routes inherit the shard-wide exposure of `/protected` writes to cross-subdomain requests (#247). It relies on Controller integration for three signed calls that declare their JSON bodies, and on the controller to deliver the link, to relay only to its own copy, and to accept a mirrored address only after mailing it (freeshard-controller#435). It relies on Identity for the default identity's name at owner creation and for the first-pairing seed, which lives in `identity.py`. It relies on the Database for the conditional `UPDATE`s that make a token single-use and a promotion guarded, for the `CHECK` constraint that pairs the token columns, and for migrations 0002 and 0005, and on Backup for a restore that keeps every user's id. From the composition root it needs the owner created after the default identity and before the first request, and `email.enabled` set where no mail can be sent. Only Sundial drives the flow; web-terminal shows the controller's copy from the stored profile as the owner's email.

The OIDC provider reads the people and the verified address: `display_name` as `name`, `username` as `preferred_username`, and `users.email` as `email` with `email_verified: true`, and it treats a disabled user as absent. This module is responsible for the column holding only a verified address and for the owner's current name; the provider trusts both, and how a rename reaches apps is its design.

Of the root invariants it keeps true:

- *The lifespan order is load-bearing*: the owner row is created after the default identity, whose name it copies, and before the first pairing, which binds to it.
- *Deployment mode is explicit*: whether the module may send mail is read from `email.enabled` and never inferred from how the controller answers.
- *The controller is one signed counterparty*: its three calls go through `post_json`, which signs them and declares JSON.
- *Work that must survive a restart is a row*: the candidate and the token are columns, so a link mailed before a restart still confirms after it; the two counters are accumulators that start empty.
- *A backup restores the shard as it was*: the people and their ids come back with a restore, which keeps every app's `sub` stable. Currently broken for snapshots written by 0.40.1 to 0.41.3 that hold a terminal.

### Constraints

From the written record, each with its source:

- There is no `GET` confirmation route, because mail scanners and link prefetchers would spend the single-use token before the owner does (#220).
- Whether the shard can send mail is never inferred from a failed delivery (the comment on `EmailSettings` in `settings.py`, #220).
- There is no synthetic `owner@<domain>` fallback: with no verified address the provider emits no email claim (#220).
- The identity carries no personal address, because `GET /public/meta/whoareyou` publishes it unauthenticated (migration 0005, #220).
- The confirm route answers identically whether or not the token matched (#220).
- Every writer of `pending_email` retires the token when it replaces the candidate (agents.md).
- User ids are plain database ids, not derived from the shard's identity (the maintainer on PR #147).
- The confirm route is unauthenticated, and the token is its only credential (#220).
- With mail off, an address is taken as typed (#220, README).
- Naming the mail switch after the deployment was rejected (5101509, PR #221).
