---
name: freeshard-research-frontier
description: "Open research problems where Freeshard can advance the state of the art, led by the personal-agent-on-shard bet ('your apps are your agent's tools and memory'). Use when asked to explore, prototype, or evaluate frontier work: agent apps on shards, always_on apps, public webhook paths, apps-as-principals token scoping, invisible self-hosting UX, cold-start/PAUSED-PAGED economics (#81/#109/#26), or the self-developing-repo loop. TRIGGER on: 'agent app', 'AI on the shard', 'always_on', 'moat', 'Olares', 'Letta', 'Goose', 'personal agent', 'research direction', 'what makes Freeshard different', 'cold start', 'PAUSED tier', RFC issues #81 #109 #110 #26. SKIP when implementing the OIDC provider itself (use freeshard-oidc-identity-campaign), when doing routine issue work (freeshard-change-control), when you need auth/crypto theory (freeshard-domain-reference), or evidence/method discipline (freeshard-research-methodology)."
---

# Freeshard research frontier

Open problems where this project can plausibly do something nobody else has done.
Written 2026-07-03. **Everything in this file is open / candidate / marinating — none
of it is roadmap.** Do not present any of it as committed work, and do not start
building any of it without a triaged issue and (for anything novel) an approved spec —
see freeshard-change-control. This skill exists so that frontier-flavored tasks start
from the maintainer's actual thesis and the platform's *verified* capabilities instead
of re-deriving them.

**Terms** (defined once):

| Term | Meaning |
|---|---|
| shard | A single-tenant customer VM running this repo's software (shard_core) + Traefik + Postgres + web-terminal, one per person |
| shard_core | This repo: FastAPI control plane on each shard; installs/runs apps as Docker Compose projects |
| app | A catalog entry from the app-repository sibling repo: `docker-compose.yml.template` + `app_meta.json`, installed onto a shard |
| forwardAuth | Traefik middleware: every request to an app is first sent to shard_core `GET /internal/auth`, which allows or denies it |
| pairing | How a browser becomes a trusted "terminal": pairing code → long-lived JWT cookie. On Freeshard, `private` means "only paired devices" |
| controller | freeshard-controller (separate, **private** repo): central cloud management, billing, provisioning |
| Max / max-tet | Owner, sole maintainer, only merge gate |
| Olares, Letta, Goose | External projects discussed below as competitive context |

Maturity labels used throughout: **[open]** = problem stated, no accepted approach.
**[candidate]** = an approach exists, unproven here. **[marinating]** = deliberately
not being built yet; strategic bet under discussion.

---

## Frontier 1 (LEAD): the personal agent on the shard — [marinating]

**Thesis (maintainer's, per internal analysis 2026-06, discussed with co-founder):**
a personal AI agent running *as an app on the user's own shard* is a defensible moat,
because **your apps are your agent's tools and memory**. Paperless-ngx = document
memory, Immich = photo/visual memory, Vaultwarden = secrets, File Browser = files —
all already single-tenant, on hardware the user pays for, behind an identity the
platform controls. This is deliberately **marinating**: pricing, BYO-key vs resold
tokens, and productization are all undecided. Treat every task in this area as
research, not feature work.

### Why current state of the art fails here (competitive claims, as of 2026-07-03)

| Player | What they prove | Why they don't own this |
|---|---|---|
| Hosted agents (ChatGPT/Claude-style assistants) | Demand for capable agents | They don't own the user's data plane; every integration is a per-service OAuth grant to a third party's cloud (assessment, unverified) |
| Local-first agents (desktop apps, home-lab LLMs) | Demand for private AI | No always-on compute, no curated app ecosystem to act as tools/memory (assessment, unverified) |
| Olares (beclab/Olares, AGPL-3.0, "An Open-Source Personal Cloud to Reclaim Your Data" — repo verified via `gh api repos/beclab/Olares`) | Consumer demand for sovereign personal-cloud AI exists; they ship a hardware box ("Olares One" — product details unverified this session) | Not agentic: apps are not wired up as an agent's tools (assessment as of 2026-07-03, unverified) |
| Letta (letta-ai/letta, Apache-2.0, "Platform for stateful agents" — verified via `gh api`) | Embeddable open-source agent engine with memory | Engine without a platform: no user-owned box, no app catalog, no identity layer. Complement, not competitor — a candidate to embed |
| Goose (block/goose → redirects to aaif-goose/goose, Apache-2.0 — verified via `gh api`) | Same: open, extensible agent engine | Same. Candidate to embed |

The gap Freeshard sits in: **single-tenant always-on box + curated app catalog +
platform-owned identity**. Nobody listed above has all three.

### What the platform ALREADY supports (verified in this repo, zero core changes)

An agent app can be built today as an ordinary catalog or custom app. Verified
capabilities:

| Capability | Mechanism | Verified at |
|---|---|---|
| Stay running (no idle-sleep) | `app_meta.json` → `lifecycle: {"always_on": true}`. Validator forbids combining with `idle_time_for_shutdown`; the periodic `control_apps` task (re)starts always_on apps if the VM size fits | `shard_core/data_model/app_meta.py:90-110`, `shard_core/service/app_lifecycle.py:59-61` |
| Accept unauthenticated inbound (webhooks, agent API with its own token auth) | `app_meta.json` path with `"access": "public"`. Note: forwardAuth still *fires* on every request — public paths are **granted with anonymous auth state** (`X-Ptl-Client-Type: anonymous`), they don't bypass the middleware | `shard_core/data_model/app_meta.py:23-26,79-81`, `shard_core/web/internal/auth.py:88-111`; test `test_headers` in `tests/test_auth.py:45-63` asserts a `/public` path returns 200 with `X-Ptl-Client-Type: anonymous` |
| Know who's calling | Per-path header templates inject `X-Ptl-Client-Type/-Id/-Name` (terminal / peer / anonymous) into proxied requests | `shard_core/web/internal/auth.py:102-105` |
| Email the owner (and ONLY the owner) | App on the `portal` Docker network → `http://shard_core/internal/call_backend/api/email_relay` → shard-signed proxy → controller `POST /api/email_relay` (recipient fixed to shard's `owner_email`, per-shard hourly rate limit, default 10/h, audited). No general SMTP from shards, by design | `shard_core/web/internal/call_backend.py:24-49`; controller side `freeshard_controller/api/email_relay.py` (private repo, verified on remote main 2026-07-03) |
| Be installed without catalog publication | `POST /core/protected/apps` accepts a custom app zip upload | `shard_core/web/protected/apps.py:107-108` (validation gaps tracked in P1 issue https://github.com/FreeshardBase/freeshard/issues/107) |
| Be size-gated | `minimum_portal_size` vs shard VM size | `shard_core/data_model/app_meta.py:125`, `shard_core/service/app_tools.py:141-149` |

**Cost model of `always_on`:** idle-sleep normally stops containers, freeing RAM;
an always_on app's cost is *held RAM* on the smallest tiers. XS ≈ 2 GB RAM on current
OVH flavors (unverified as of 2026-07-03 — the size→flavor mapping is a controller
*runtime setting*, `settings.ovhcloud.vm_sizes` in the private controller repo's
`service/cloud_adapter/ovh.py:67`, not committed config; measure, don't assume). This
is the open pricing question (flat tier uplift vs metered) — undecided.

**Security nuance worth knowing (moat-relevant):** `/internal/*` routes are not
reachable through Traefik (only `/core/public|protected|management` and app hosts are
routed — `shard_core/service/traefik_dynamic_config.py:45-66,168`), but any app on the
`portal` Docker network can call `/internal/call_backend/...` and thereby act with the
**shard's full authority** against the controller. There is no per-app identity today.
That is exactly the hole apps-as-principals (below) is meant to close — and a reason
the agent bet depends on the OIDC campaign.

### The moat mechanism: apps as principals — [candidate], gated on OIDC campaign

The embedded OIDC identity provider (see **freeshard-oidc-identity-campaign** — that
skill owns all decisions there) would make each app a first-class OAuth client of the
shard. Then the agent app gets **scoped tokens per app**: a token that can read
Paperless documents but *cannot* touch Immich or Vaultwarden. The PoC already contains
the hook: the spike's `OidcClient` model carries a per-client `scope` string and
`get_allowed_scope()` filtering (`.worktrees/spike-oidc-poc/shard_core/service/oidc_provider.py:55-89`,
branch `spike/oidc-provider-poc`, local worktree only, **not pushed to origin** as of
2026-07-03). Nothing about agent-facing scoping is designed yet — do not invent scope
taxonomy ahead of that campaign's decision gates.

Adjacent idea parked with it **[open]**: shard as MCP client / AI-discovery-via-DNS
(co-founder suggestion, 2026-06) — recorded, unexplored.

### First three concrete steps IN THIS REPO (feasibility verified)

1. **Prototype an agent app using the existing mock-app test pattern.** The test
   fixture `mock_app_store(mocker)` (`tests/conftest.py:374-395`) installs apps from
   `tests/mock_app_store/<name>/<name>.zip`; a mock app with `always_on: true` **and a
   public path already exists** (`tests/mock_app_store/always_on/app_meta.json`) and is
   exercised by `tests/test_app_lifecycle.py:80` (`test_always_on_app_starts`). Copy
   that shape: always_on lifecycle + one `public` webhook path + one `private` UI path,
   containers doing their own bearer-token check on the public path. Sanity check:
   `.venv/bin/python -m pytest tests/test_app_lifecycle.py tests/test_auth.py --collect-only -q`
   (5 tests collected as of 2026-07-03). Follow freeshard-testing-and-qa for fixture rules.
2. **Define apps-as-principals token scoping on top of the OIDC client model** —
   a written design mapping app → OIDC client → allowed scopes, building on
   `OidcClient.scope` / `get_allowed_scope()` in the spike. This is a spec task
   (a Max-approved spec posted on the issue — the freeshard-intent-capture skill
   automates that flow where available), not a coding task, and must not front-run
   freeshard-oidc-identity-campaign's gates.
3. **Measure the always-on RAM envelope on the smallest tiers** to inform pricing.
   Baseline the stack, then add an always_on app and diff:
   `docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}'` on a dev compose
   stack (see freeshard-run-and-operate) or, for a real customer-shaped number, an XS
   shard via the diagnostics API (read-only, operator-activated).
   Deliverable: MB held per app state (stopped /
   idle-running / active), headroom left on XS/S. Use freeshard-diagnostics-and-tooling
   for measurement discipline.

### Falsifiable milestone

You have a **result** (not before) when: *an agent app installed on a dev stack
answers a natural-language question whose answer requires Paperless-ngx content, using
a scoped token — and the same token, presented to Immich, is refused.* Weaker interim
demo (phase-0, no OIDC dependency): same question answered using Paperless's own API
token held by the agent app — proves tools/memory value, proves nothing about the moat.
If the scoped-token demo can't be made to work on top of the OIDC campaign's client
model, the moat mechanism as currently imagined is falsified and the thesis needs
rework — say so plainly rather than shipping a demo with an unscoped token.

---

## Frontier 2: invisible self-hosting UX — [candidate]

Thesis: self-hosting wins when it disappears — "one identity, one access" as *the*
sovereignty feature. Freeshard's angle vs prior art (Sandstorm, Cloudron, Umbrel —
**comparative claims unverified**, treat as hypotheses to check before repeating):
**pairing is the auth boundary**. `private` = "only my paired devices", which is a
*stronger* gate than app-level login, so apps with built-in auth can default to
`access: private` + open registration, and login can be removed rather than added.
Real flagship metas confirm the pattern (verified in app-repository sibling):
paperless-ngx root `private` with `/share/` public; vaultwarden root `public` (does
its own auth) with `/admin/` private; immich root `public`.

The zero-click endgame is the OIDC campaign's seamless-SSO PoC (Immich login with no
click, spike branch above). Open sub-problems: which flagship apps can honor
OIDC-claims-based auto-provisioning (upstream PR dependency for Paperless — status
unknown as of 2026-07-03); expectation management for non-flagship apps (two-tier
store, RFC https://github.com/FreeshardBase/freeshard/issues/110, open, needs-Intent).

## Frontier 3: cold-start economics — [open]

The counterweight to `always_on`: idle apps hold nothing, but cold starts hurt UX, and
always-on holds RAM that XS/S tiers don't have. Live threads, all open as of
2026-07-03, all P3/needs-Intent (i.e. spec before code):

| Issue | Idea |
|---|---|
| https://github.com/FreeshardBase/freeshard/issues/81 | PAUSED+PAGED app tier (tracker) — states between RUNNING and STOPPED |
| https://github.com/FreeshardBase/freeshard/issues/109 | RFC: SQLite-first apps, container tuning, host-level zswap |
| https://github.com/FreeshardBase/freeshard/issues/26 | Manage shard resources using slices (open since 2026-01) |

Candidate mechanism under #81: `docker pause` + swapping frozen pages out (cost of a
paused app → disk instead of RAM). **Cautionary prior:** an earlier swap-tuning
experiment on another provider (Netcup) thrashed a server into an unrecoverable state.
Any experiment here goes on a disposable OVH instance, never a customer shard, with a
measured hypothesis first (freeshard-research-methodology). Related shipped groundwork:
idle-sleep already exists (`shard_core/service/app_lifecycle.py`), and its known UX
traps (PWA service workers lying to the splash screen, apps that 200 before ready) are
chronicled in freeshard-failure-archaeology.

## Frontier 4: the self-developing repo — [candidate, partially live]

The development process itself is a research object: triage (board grooming) →
overnight grind (one fresh headless agent session per issue, own worktree, branch from
main) → human review as the only ship gate. It demonstrably ships real fixes end-to-end
(e.g. https://github.com/FreeshardBase/freeshard/pull/106 and
https://github.com/FreeshardBase/freeshard/pull/119 — authored by ClaydeCode, merged;
verified via `gh pr view`). Mechanics and non-negotiables live in
freeshard-change-control — this skill only states the frontier question:

**Milestone:** identify an *issue class* (e.g. dependency refreshes, doc-drift fixes,
test-gap fills) that ships end-to-end with **review-only** human time — no triage
back-and-forth, no intent capture, no mid-flight correction — sustained over multiple
instances. Until a class clears that bar repeatedly, claims of "self-developing" are
oversell; the honest current state is "agent-developed, human-gated."

---

## Rules of engagement for frontier work

1. **Nothing here bypasses change control.** Frontier prototypes live in worktrees /
   spike branches, never merge without Max, and RFC-class ideas need a spec (Needs
   Intent flow) first. freeshard-change-control wins every conflict with this file.
2. **Label maturity in everything you write.** open / candidate / marinating, as
   above. The agent bet especially: it is a *bet under discussion*, not a plan.
3. **Competitor and market claims decay fast.** Anything about Olares/Letta/Goose or
   hosted-agent capabilities must be re-verified (or re-labeled unverified) before it
   leaves this repo — see freeshard-docs-and-positioning for external-claims discipline.
4. **Hypotheses must predict numbers before you measure** (RAM envelopes, cold-start
   latencies) — freeshard-research-methodology has the evidence bar.
5. **Don't burn customer shards.** Experiments run on dev stacks or disposable OVH
   instances; customer-shard inspection only through the read-only diagnostics flow.

## When NOT to use this skill

- Implementing or deciding anything about the OIDC provider → **freeshard-oidc-identity-campaign** (this file only consumes its outputs).
- Ordinary assigned-issue work, PRs, releases → **freeshard-change-control**.
- How pairing/JWT/signatures/forwardAuth actually work → **freeshard-domain-reference**.
- Running the stack or a dev server to try something → **freeshard-run-and-operate**.
- Writing the tests for a prototype → **freeshard-testing-and-qa**.
- Turning a hunch into an accepted result (method, evidence bar) → **freeshard-research-methodology**; analysis recipes → **freeshard-proof-and-analysis-toolkit**.
- History of why past ideas died → **freeshard-failure-archaeology**.
- Cross-repo contracts (controller relay, app-repository metas) mechanics → **freeshard-ecosystem-contracts**.

## Provenance and maintenance

Written 2026-07-03 against shard_core working tree (branch `fix-profile-billing-fields`,
v0.39.2 checkout; origin/main head `0a40684`). Primary public sources: this repo's
source and tests at the cited file:line locations; app-repository sibling checkout;
GitHub issues/PRs cited by URL; `gh api` reads of beclab/Olares, letta-ai/letta,
block/goose. The maintainer-thesis and pricing/marinating status statements come from
internal project analysis (2026-06) and are dated accordingly.

Drift-prone facts — re-verify before relying:

| Fact (as of 2026-07-03) | Re-verify with |
|---|---|
| `always_on` / `idle_time_for_shutdown` validator semantics | `grep -n "always_on" shard_core/data_model/app_meta.py shard_core/service/app_lifecycle.py` |
| Public paths get anonymous grant (forwardAuth fires, doesn't 401) | `sed -n '74,112p' shard_core/web/internal/auth.py` |
| Mock always_on app + its test exist | `ls tests/mock_app_store/always_on/ && grep -n always_on tests/test_app_lifecycle.py` |
| Custom-app zip upload endpoint exists | `grep -n "install_custom_app" shard_core/web/protected/apps.py` |
| `call_backend` proxy signs with full shard authority, no per-app auth | `sed -n '24,50p' shard_core/web/internal/call_backend.py` |
| Controller email relay exists on main (private repo) | `gh api "repos/FreeshardBase/freeshard-controller/contents/freeshard-controller-backend/freeshard_controller/api/email_relay.py?ref=main" --jq .name` |
| OIDC spike branch state (local-only worktree) | `git branch -a \| grep -i oidc; git ls-remote origin \| grep -i oidc` |
| Issues #26/#81/#109/#110 still open | `for n in 26 81 109 110; do gh issue view $n --repo FreeshardBase/freeshard --json state,title --jq '"\(.state) \(.title)"'; done` |
| ClaydeCode-authored merged PRs (#106/#119) | `gh pr view 106 --repo FreeshardBase/freeshard --json author,state` |
| Olares/Letta/Goose license + description | `gh api repos/beclab/Olares --jq '{license: .license.spdx_id, desc: .description}'` (likewise letta-ai/letta, block/goose) |
| Flagship app path/lifecycle patterns | `python3 -c "import json; m=json.load(open('../app-repository/apps/paperless-ngx/app_meta.json')); print(m['paths'], m['lifecycle'])"` |
