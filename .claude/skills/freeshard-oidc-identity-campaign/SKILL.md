---
name: freeshard-oidc-identity-campaign
description: "Executable, decision-gated campaign to productionize the embedded OIDC identity provider inside shard_core (Authlib), replacing the rejected Authelia direction. TRIGGER on: OIDC, OpenID Connect, SSO, single sign-on, identity provider, IdP, Authlib, authorization code, PKCE, id_token, JWKS, discovery document, redirect_uri, 'zero-click login', Immich login, spike/oidc-provider-poc, shard_core/service/oidc_provider.py, shard_core/web/public/oidc.py, tests_poc/, Authelia, PR #86, issue #36, 'pairing session bridge'. SKIP when the task is about the existing terminal-pairing JWT auth or Traefik forwardAuth as-is (use freeshard-domain-reference), general auth debugging (freeshard-debugging-playbook), or generic release mechanics (freeshard-change-control)."
---

# Freeshard OIDC Identity Campaign

Mission: give every shard a built-in OpenID Connect provider so installed apps
(Immich first) log the owner in with **zero clicks**, riding on the existing
terminal-pairing session. This is the hardest live problem in the repo. This
skill is the campaign plan: numbered phases, each ending in a GATE with exact
commands and expected observations.

**Vocabulary** (project terms, defined once):

| Term | Meaning |
|---|---|
| shard | One customer VM running shard_core (FastAPI) + PostgreSQL + Traefik + per-app Docker Compose stacks |
| terminal | A paired browser/device. Pairing = redeem a 6-digit code at `POST /public/pair/terminal`, get an HS256 JWT in an `authorization` cookie (no `exp`; revoked by deleting the terminal row) |
| forwardAuth | Traefik middleware calling `GET /internal/auth` on every app-subdomain request; enforces per-path `access: private/peer/public` from the app's `app_meta.json` |
| pairing-as-auth-boundary | Freeshard design decision: "private" means *only my paired devices* — a stronger gate than app-level login. The OIDC provider extends this: a paired session IS the login |
| the spike | Local branch `spike/oidc-provider-poc` (4 commits, 2026-06-12), worktree `.worktrees/spike-oidc-poc`. Reference only — production work happens on a FRESH branch |

## Decision context (settled — do not relitigate without Max)

- **Decided 2026-06-12**: identity = embedded OIDC provider inside shard_core
  using **Authlib**, NOT Authelia. Method: a solution-neutral requirements
  brief was given to a fresh AI session with zero hints; it re-derived Authelia
  as a candidate and still recommended embedding. Drivers: restart-free config
  (Authelia needs restarts/reloads on client changes), memory footprint on 1GB
  XS VMs, passwordless pairing-based onboarding, and the no-email constraint
  (shards have no general outbound email by design; apps can only mail the
  owner via the controller relay).
- **Same-day PoC**: ~740 LoC of provider code + 13 integration tests + a
  live deployment achieving zero-click Immich login. See Phase 0.
- **Known counter-risk (maintainer-acknowledged, not waved away)**: a
  self-built IdP carries crypto unknown-unknowns, in a public repo that is
  trivially scannable by AI tooling. This does not reverse the decision; it
  creates the explicit security obligations in Phases 1 and 6.

### Fenced-off wrong paths — do NOT go here

| Dead path | Status as of 2026-07-03 | Rule |
|---|---|---|
| Authelia as core IAM | PR https://github.com/FreeshardBase/freeshard/pull/86 still OPEN, zero reviews; its issue https://github.com/FreeshardBase/freeshard/issues/36 was bulk-closed 2026-06-29. The PR is orphaned. | Do not revive, rebase, or borrow architecture from it without a NEW recorded decision from Max. If asked to "finish #86", surface this fence first. |
| Per-app SSO patches | — | No app-specific auth hacks (custom header trust, per-app reverse-auth shims). Apps integrate via standard OIDC or not at all. |
| Rolling your own JOSE | — | No hand-implemented JWT signing/verification, PKCE hashing beyond `hashlib.sha256` for test helpers, or key generation outside Authlib/joserfc. Verified gate in Phase 6. |
| Vaultwarden SSO | — | Known to WORSEN login UX (SSO still demands the master password on top; its SSO exists for enterprise deprovisioning). Fenced out of rollout scope — see Phase 5. |
| Merging the spike | — | The spike is reference material. Production implementation is a fresh branch off main; copy ideas, not commits. |

---

## Phase 0 — Read the spike (inventory, ~30 min)

The spike branch exists **only locally** in this checkout (not on
`origin` as of 2026-07-03 — `git ls-remote origin | grep oidc` returns
nothing). It lives at branch `spike/oidc-provider-poc`, checked out in
worktree `.worktrees/spike-oidc-poc`.

```bash
git log --oneline main..spike/oidc-provider-poc        # expect 4 spike commits (fb7f914..1d4ca85) + whatever main lacks
git diff main...spike/oidc-provider-poc --stat          # ~30 files; provider core is 4 files
git show spike/oidc-provider-poc:shard_core/service/oidc_provider.py   # 388 lines: Authlib server, grants, key mgmt
git show spike/oidc-provider-poc:shard_core/web/public/oidc.py         # 184 lines: FastAPI adapter + endpoints
git show spike/oidc-provider-poc:shard_core/database/oidc.py           # 151 lines: sync psycopg storage
git show spike/oidc-provider-poc:migrations/shard-core-0002-oidc.sql   # 3 tables: oidc_clients, oidc_codes, oidc_tokens
git show spike/oidc-provider-poc:tests_poc/test_oidc_poc.py            # 13 tests
git show spike/oidc-provider-poc:deploy/poc-compose.yml                # live PoC deployment (Immich, no ML)
```

GATE 0: all commands above succeed and the file line counts roughly match.
If `spike/oidc-provider-poc` is unknown → the local branch was pruned; look
for the worktree (`git worktree list | grep spike`), then ask Max where the
spike went before proceeding. Do NOT reconstruct it from memory.

### What the spike PROVED vs what it STUBBED (verified against the branch)

| Proved (evidence on branch) | Stubbed / unproven (do not assume) |
|---|---|
| Authlib code+PKCE+refresh flow works against real Postgres — 13 green integration tests in `tests_poc/` (discovery, JWKS, confidential + public-client flows, userinfo, refresh rotation, wrong-redirect-uri → 400 not redirect, wrong secret → 401, unknown/expired code → 400, code reuse → 400, anonymous → login redirect, scope narrowing) | Tests live in `tests_poc/` with their own conftest (session-scoped loop, external Postgres on :5432) — deliberately NOT integrated with the main `tests/` suite or CI |
| Zero-click Immich login end-to-end on a live deployment: paired cookie → `/authorize` → code → Immich session, 0 clicks / 0 keystrokes (playwright script `scripts/oidc_poc_browser_test.py`, deployment `deploy/poc-compose.yml`) | The deployment used a slim app (`scripts/oidc_poc_app.py`) with only the public router and a hand-rolled pairing page — NOT the real shard stack behind Traefik with `/core/` prefix stripping |
| Pairing-session bridge concept: `/authorize` accepts the `authorization` terminal-JWT cookie via `pairing.verify_terminal_jwt`; anonymous browsers 302 to `/?oidc_rd=<authorize-url>` | The `oidc_rd` return redirect is UNVALIDATED in the PoC pairing page (open-redirect if copied as-is); the real login/pairing UI belongs to web-terminal and does not exist yet |
| Separate RS256 signing key (RSA-2048 via joserfc), private JWK persisted in `kv_store` key `oidc_provider_jwk`; JWKS endpoint never leaks `d` (tested) | No key rotation, single kid forever; private JWK stored plaintext (same posture as identity private_key — but see Phase 1 obligation) |
| Immich specifics: needs an email claim to auto-provision (spike synthesizes `owner@{domain}`); sends `client_secret_post`; strict about `nonce: null` vs absent (spike strips null claims); redirect URIs `/auth/login`, `/user-settings`, `app.immich:///oauth-callback`; OAuth auto-launch configurable via API (`scripts/oidc_poc_immich_setup.py`) | Client registration is manual (setup script calls `register_client()`); no wiring into app installation, no `app_meta.json` contract, no secret delivery to app containers |
| Scope escalation blocked at the grant layer (uses `request.scope` resolved against registered scope, not raw payload — see comment in `save_authorization_code`) | Token revocation on terminal unpair: tokens carry `user_sub` only, no terminal linkage — unpairing a device revokes NOTHING in the spike |
| Single-user mapping is forward-compatible: `sub` = default identity id (stable across a future multi-user rollout) | Multi-user, consent UI, logout/end_session endpoint, token-endpoint rate limiting, `plain` PKCE lockdown — all absent |
| Sync-Authlib-in-async-FastAPI bridge: `asyncio.to_thread` + pre-built `OAuth2Request` + `CaseInsensitiveDict` headers shim | Storage opens a new sync psycopg connection per call — the module docstring itself says "revisit before productizing" |

Also true: `authlib>=1.7.2` is a spike-only dependency — main's
`pyproject.toml` has no authlib (verify: `grep authlib pyproject.toml`).

---

## Phase 1 — Requirements freeze + threat model

Before writing code, produce a threat model as an intent spec on the GitHub
issue (see Phase 7 for the issue workflow). Each row below is an
**obligation to derive and write down an answer**, not a to-do to silently
implement. The AI-scannable-public-repo risk means every one of these will
eventually be read by an adversary with a static analyzer.

| Threat | Spike posture (verified) | Derivation obligation for the spec |
|---|---|---|
| Redirect-URI manipulation | Exact string match against registered list; mismatch → 400, never a redirect (tested) | Keep exact match, no wildcards, no substring/prefix logic. State why (open-redirect + code exfiltration). |
| Session fixation / pairing brute force | Pairing code = 6 digits, single active code, 600 s TTL, single-use, but `POST /public/pair/terminal` has NO rate limit | Derive attack math (10^6 space vs request rate) and decide: rate limit, longer code, or accept + document. The OIDC provider inherits whatever pairing's strength is — it IS the login. |
| Token substitution / audience | id_token `aud=[client_id]`; access tokens are opaque random strings bound to client_id in DB; but `/userinfo` accepts ANY valid access token (client-agnostic) | Prove or bound: can app A's token do anything at app B? Single-user today makes this low-stakes — write the argument down so multi-user work re-opens it. |
| Signing-key storage | Private JWK plaintext in Postgres `kv_store` (`oidc_provider_jwk`) — same posture as identity `private_key` and `terminal_jwt_secret` | Decide: accept (consistent with existing posture, documented) or encrypt at rest. Don't silently diverge from repo posture either way. |
| Identity key vs OIDC signing key | Spike uses a SEPARATE RSA-2048 RS256 key, not the RSA-4096 identity key (`shard_core/service/crypto.py` — note: the repo's crypto is RSA-4096 with PSS, HTTP signatures RSA_PSS_SHA512; agents.md's "Ed25519" claim is wrong) | Recommend keeping separation: independent rotation, smaller blast radius, no cross-protocol key reuse. Record as an explicit decision. |
| Key rotation | None — one key, one kid, forever | Design rotation: generate new key, publish old+new in JWKS for a grace window, sign with new. Decide trigger (manual? age?). May ship post-v1 but must be *designed* pre-v1 so storage schema allows multiple keys. |
| Clock skew | Authlib default iat/exp handling; codes expire via DB `expires_at > now()` | State the assumption: provider and RP run on the SAME VM (same clock) for first-party apps — skew is a non-issue until remote RPs exist. Write that boundary down. |
| Open redirect via `oidc_rd` | PoC pairing page does `location.href = rd` unvalidated | Production login page (web-terminal) MUST validate `oidc_rd` is a same-origin path to the authorize endpoint. Cross-repo obligation — flag it in the spec. |
| PKCE downgrade | `CodeChallenge(required=True)` but discovery advertises `plain` alongside `S256` | Require S256 only in production; remove `plain` from discovery and enforcement. |
| Docker-network bypass | Any installed app shares the `portal` network and can reach `http://shard_core/...` directly, skipping Traefik (known repo weak point — see freeshard-architecture-contract) | Token endpoint is gated by client secret, so direct reach is survivable — derive this explicitly. Also decide how apps receive their client secret (Phase 2 D). |
| Refresh-token reuse | Rotation on every refresh; rotated-out token → 400/401 (tested); refresh lifetime hack: 24× access-token lifetime | Decide real refresh lifetime + whether reuse of a rotated-out token revokes the whole token family (recommended standard practice). |
| Revocation on unpair | Absent — tokens have no terminal linkage | Design it: record the issuing terminal_id on codes/tokens; deleting a terminal revokes its tokens. This is a Phase 4 milestone with a test. |

GATE 1: the spec exists as a comment on the campaign's GitHub issue and Max
has approved it (post the spec as an issue comment and wait for approval; the
freeshard-intent-capture skill automates this flow where available). If Max pushes back on
any row → the spec changes, not the fence. No code before this gate.

---

## Phase 2 — Architecture decision points (ranked menu)

Present these to Max in the spec; ranked = recommended first. The issuer URL
gets baked into every app's OIDC config, so **A must be decided before any
app rollout** — changing issuer later is a fleet migration.

**A. Where the provider mounts**
1. *(spike-proven, least change)* Under the existing public router:
   FastAPI path `/public/oidc/...`, external URL
   `https://<domain>/core/public/oidc/...` (Traefik strips `/core/`;
   the `auth-public` middleware only injects headers, never blocks — the
   `authorization` cookie flows through untouched). Ugly issuer, zero Traefik
   changes. The spike needed a `SHARD_OIDC_ISSUER` env override because its
   slim deployment had no `/core` strip — production on this option must
   compute issuer as `https://{identity.domain}/core/public/oidc` and the
   override should remain a dev-only escape hatch.
2. Dedicated Traefik router for a clean issuer (`https://<domain>/oidc` or
   root-level `/.well-known/...`): nicer, but touches
   `shard_core/service/traefik_dynamic_config.py` (compiled Python config —
   see freeshard-domain-reference) and adds a new auth level to reason about.
3. Subdomain `oidc.<domain>`: cookie still arrives (pairing cookie is set
   with `domain=identity.domain`), but a new router + cert surface for little
   gain.

**B. Signing key** — keep the spike's separate-key choice (see Phase 1 row).
Alternative (reusing the RSA-4096 identity key) is ranked last: couples
identity rotation to token validity and reuses one key across two protocols.

**C. Per-app client registration model**
1. *(recommended)* Install-time hook: the app-installation worker
   (`shard_core/service/app_installation/`) reads an `oidc` block from
   `app_meta.json` (contract to be defined — Phase 5), calls
   `register_client(...)`, and injects `client_id`/`client_secret` into the
   app's compose template variables (the existing jinja2 `portal.*`/`fs.*`
   mechanism). Uninstall deletes the client and revokes its tokens.
2. Manual/API registration: fine for dev, not a product.
   The spike's `register_client()` is REPLACE-on-conflict by app_name — keep
   that idempotence for reinstalls.

**D. Storage layer** — the spike's per-call sync psycopg connections must be
revisited (its own docstring says so). Options: small dedicated sync
`psycopg_pool.ConnectionPool` for the to-thread'd Authlib hooks
*(recommended — bounded, simple)*; or rework hooks to async (fights
Authlib's sync core; not worth it). Remember the repo invariant: the
forwardAuth hot path must stay zero-DB-query
(https://github.com/FreeshardBase/freeshard/pull/90) — OIDC endpoints are
NOT on that path, but don't add OIDC lookups to `/internal/auth`.

**E. Discovery + JWKS placement** — keep OIDC-standard shape:
`{issuer}/.well-known/openid-configuration` and `jwks_uri` under the issuer,
exactly as the spike does. Strict RPs derive the well-known URL from the
issuer string; do not invent nonstandard paths.

GATE 2: each of A–E has a recorded decision in the approved spec. If a
decision is still open when implementation pressure mounts → stop and get
the decision; a guessed issuer or registration model is rework, not progress.

---

## Phase 3 — Skeleton + tests on a fresh branch (TDD)

```bash
git checkout main && git pull
git worktree add .worktrees/oidc-provider -b feature/clayde/oidc-provider  # agent naming per freeshard-change-control §3
cd .worktrees/oidc-provider && uv sync --extra dev                  # ALWAYS --extra dev (pytest/ruff); never symlink .venv
```

Order of work (write the failing test first — use the superpowers:test-driven-development skill if your session has it):

1. **Migration**: next `migrations/shard-core-NNNN-<slug>.sql` with yoyo
   headers (`-- <id>` / `-- depends: <previous>`). As of 2026-07-03 main has
   only `shard-core-0001-init.sql`, but other in-flight worktrees may claim
   0002 — check `git fetch && git ls-tree origin/main migrations/` AND open
   PRs before picking the number. Start from the spike's three tables
   (`oidc_clients`, `oidc_codes`, `oidc_tokens`) plus whatever Phase 1
   decided (terminal_id column for revocation, multi-key storage).
2. **Service + web layer**: port `oidc_provider.py` / `web/public/oidc.py`
   ideas deliberately, applying Phase 1/2 decisions (S256-only, issuer
   computation, storage pool). Add `authlib` to `pyproject.toml` deps.
3. **Tests in the MAIN suite** (`tests/`, not a new `tests_poc/`): the main
   conftest gives you pytest-docker Postgres 17 (port 5433) with all tables
   truncated before each test — the spike's unique-app_name workaround is
   unnecessary there. Use the `app_client` fixture (app without lifespan,
   DB + default identity, no Docker) for protocol tests; see
   freeshard-testing-and-qa for fixture decision rules. Port ALL 13 spike
   test behaviors — they are the regression floor, not the ceiling — and add
   the Phase 1 obligations (S256-only, revocation-on-unpair once built).
4. **Zero-click flow test** at the HTTP level: paired-cookie client hits
   `/authorize` → 302 with code; anonymous client → 302 to login with
   `oidc_rd`. The spike's `tests_poc/conftest.py` shows how to mint a
   terminal session in-test (`Terminal.create` + `db_terminals.insert` +
   `pairing.create_terminal_jwt`).

Run: `pytest tests/ -k oidc` and the full suite; `just cleanup` before commits.

GATE 3: full test suite green locally AND in CI on the PR branch
(`gh pr checks <n>`). If tests pass locally but CI fails on dependency
resolution → check CI installs from lockfile (`uv sync --frozen`;
https://github.com/FreeshardBase/freeshard/issues/114 history).

---

## Phase 4 — Pairing-session bridge (the novel part)

This is the piece with no off-the-shelf precedent: **paired-terminal cookie →
authorization code, with no login UI ever shown**. Everything else is
standard OIDC; this is where reviewers must look hardest.

Mechanism (spike-proven shape): `/authorize` reads the `authorization`
cookie → `pairing.verify_terminal_jwt` (HS256, secret in kv_store, terminal
row must exist) → resource owner = shard owner → Authlib issues the code
immediately (first-party clients, no consent screen). Anonymous → 302 to the
web-terminal login/pairing page with `oidc_rd=<full authorize URL>`.

**What proves the bridge safe** (each becomes a test or a spec paragraph):

1. An expired/garbage/absent cookie NEVER yields a code — only the login
   redirect. (Spike test: `test_anonymous_authorize_redirects_to_login`.)
2. A cookie for a DELETED terminal is rejected — `verify_terminal_jwt`
   already enforces row existence; add an explicit test (unpair → authorize
   → login redirect, not code).
3. Unpairing a terminal revokes the OIDC tokens it minted (Phase 1 design;
   NOT in the spike). Test: full flow, delete terminal, assert refresh →
   401 and userinfo → 401 within the access-token lifetime or immediately,
   per the spec's decision.
4. `oidc_rd` on the web-terminal side only ever navigates to a same-origin
   authorize path (cross-repo: web-terminal PR; see
   freeshard-ecosystem-contracts for multi-repo checklists).
5. The cookie is `httponly` + `secure` with Starlette's default
   `SameSite=Lax` (`shard_core/web/public/pair.py` sets no explicit
   samesite) — Lax sends it on top-level GET navigations, which is exactly
   the authorize redirect. Document that the bridge *depends* on Lax
   semantics; an over-eager "harden to Strict" change would silently break
   zero-click.

GATE 4: a headless-browser run on a fresh dev stack reproduces the spike's
zero-click result against the PRODUCTION implementation: 0 clicks, 0
keystrokes, logged-in Immich. Adapt `scripts/oidc_poc_browser_test.py`
(spike) — it counts interactions and asserts none. If the browser lands on
Immich's login page instead → check OAuth auto-launch in Immich config and
issuer consistency (discovery `issuer` must equal id_token `iss` must equal
the URL Immich was configured with, byte-identical).

---

## Phase 5 — App-side rollout

Define the `app_meta.json` contract (candidate shape — NOT yet designed;
agree in the spec first): an `oidc` block declaring redirect URI paths and
required claims, from which install-time registration (Phase 2 C) builds the
client and injects credentials into the compose template.

Rollout ladder, in order:

| App | Status as of 2026-07-03 | Action |
|---|---|---|
| Immich | Known-smooth. Spike wired it live: needs email claim (synthesize `owner@{domain}` when identity has none), `client_secret_post`, strips-null-nonce quirk, redirect URIs `/auth/login` + `/user-settings` + `app.immich:///oauth-callback`, auto-launch via system config API | First and reference integration. Its `app_meta.json` in app-repository gets the first `oidc` block. |
| Paperless-ngx | Open external dependency: an upstream PR for OIDC claims handling was in flight (outcome unverified as of 2026-07-03) | Check upstream before promising; fork threshold is Max's call. |
| Vaultwarden | **Fenced off.** SSO demonstrably worsens its login (master password still required after IdP) | Do not integrate. If asked, point at this fence. |
| File Browser / others | Unassessed | One at a time, only after Immich ships. |

GATE 5: Immich installs from the app store on a fresh dev stack and
zero-click login works with ZERO manual configuration steps (the
`oidc_poc_immich_setup.py` script's job is now done by install-time
registration + app config). Manual steps remaining = phase not done.

---

## Phase 6 — Hardening gate before ANY release

Run before the first version bump that contains the provider. All must pass:

```bash
# 1. No hand-rolled crypto primitives — only Authlib/joserfc/stdlib-hashlib-for-tests
grep -rn 'from cryptography' shard_core/service/oidc* shard_core/web/public/oidc* shard_core/database/oidc*   # expect: no hits
grep -rn 'jwt.encode\|jws\|jose' shard_core/ --include='*.py' | grep -vi 'authlib\|joserfc'                    # expect: no hits outside pairing.py (existing HS256 terminal JWT)
# 2. JWKS never leaks private material (also a permanent test)
pytest tests/ -k jwks
# 3. Discovery advertises S256 only
curl -s localhost:8080/public/oidc/.well-known/openid-configuration | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["code_challenge_methods_supported"]==["S256"], d'
# 4. Full suite
pytest tests/
```

Plus non-command checks: every Phase 1 obligation has a written resolution in
the spec; the open-redirect fix exists in web-terminal; revocation-on-unpair
test is green. **External security review is Max's call** — raise it
explicitly in the PR description (the counter-risk that motivated it is the
public, AI-scannable repo), don't decide for him either way.

GATE 6: all four command checks pass and Max has explicitly acknowledged the
review question. Any failure → fix before Phase 7, no exceptions.

---

## Phase 7 — Promotion through change control

Follow freeshard-change-control; summary of the non-negotiables as they apply
here:

1. Work is anchored to a GitHub issue with an approved intent spec (Phase 1).
2. PR from the feature branch; description covers the whole branch and lists
   a recommended reading order (migration → database → service → web →
   tests). Nothing auto-merges; **Max's review+merge is the only ship gate**.
3. **Merged ≠ shipped.** A release requires: `just set-version <version>`
   (bumps `pyproject.toml` + `docker-compose.yml` image tag and COMMITS —
   run on a clean tree) + a published GitHub Release (builds
   `ghcr.io/freeshardbase/freeshard:<tag>`) + the controller's core-version
   compose bump. History: https://github.com/FreeshardBase/freeshard/issues/111
   (merged fix sat unreleased),
   https://github.com/FreeshardBase/freeshard/pull/113 (version bump raced
   main — always `git fetch` and check `origin/main` + published releases
   first). Versioning may move to semver
   (https://github.com/FreeshardBase/freeshard/issues/118, open) — re-check
   before releasing.
4. NEVER auto-ship. An agent may prepare the release PR; publishing is Max's.

## Measurable success (the campaign is done when…)

1. On a fresh dev stack, Immich installed from the app store: headless
   browser with a paired-terminal cookie reaches a logged-in Immich with 0
   clicks and 0 keystrokes (Gate 4 script, now in `scripts/` as a kept tool).
2. CI-green tests prove, by name: redirect-URI rejection (400, no redirect),
   token audience (`aud == [client_id]`), code single-use, PKCE-S256
   required, scope narrowing, refresh rotation with old-token revocation,
   JWKS privacy, and **revocation on terminal unpair**.
3. `grep`-level absence of hand-rolled crypto (Gate 6 commands).
4. A released image tag contains it all, promoted per Phase 7.

Anything short of all four is "in progress", not "done" — say so plainly.

## When NOT to use this skill

- Understanding how terminal pairing, forwardAuth, RSA-4096/HTTP-signature
  crypto, or Traefik config work **today** → freeshard-domain-reference.
- Debugging a broken auth flow on an existing shard → freeshard-debugging-playbook.
- Why Authelia/other approaches were rejected, full investigation history →
  freeshard-failure-archaeology.
- Release mechanics, gate definitions, review rules in general →
  freeshard-change-control.
- Writing/structuring the tests themselves → freeshard-testing-and-qa.
- Changing `app_meta.json` handling or cross-repo contracts broadly →
  freeshard-ecosystem-contracts.

## Provenance and maintenance

Written 2026-07-03. Primary sources: local branch `spike/oidc-provider-poc`
(commits fb7f914, e09af8d, 587bd8c, 1d4ca85 — read via `git show`, never
checked out), repo files on main (`shard_core/service/pairing.py`,
`shard_core/web/public/pair.py`, `shard_core/service/crypto.py`, `justfile`,
`pyproject.toml`, `migrations/`), GitHub state via `gh`
(https://github.com/FreeshardBase/freeshard/issues/36,
https://github.com/FreeshardBase/freeshard/pull/86,
https://github.com/FreeshardBase/freeshard/issues/111,
https://github.com/FreeshardBase/freeshard/issues/118).

| Drift-prone fact | Re-verify with |
|---|---|
| Spike branch still exists locally, 4 commits, not on origin | `git log --oneline main..spike/oidc-provider-poc && git ls-remote origin \| grep -i oidc` |
| Production OIDC work not yet started on main | `git fetch && git ls-tree origin/main shard_core/service \| grep oidc` (expect empty) |
| PR #86 (Authelia) still open/orphaned | `gh pr view 86 --repo FreeshardBase/freeshard --json state,reviews` |
| Issue #36 still closed | `gh issue view 36 --repo FreeshardBase/freeshard --json state,closedAt` |
| authlib absent from main deps | `git show origin/main:pyproject.toml \| grep -i authlib` (expect empty) |
| Only migration on main is 0001 (next free number) | `git fetch && git ls-tree origin/main migrations/` |
| Pairing cookie attrs (secure, httponly, no samesite) | `grep -n -A8 'set_cookie' shard_core/web/public/pair.py` |
| Terminal JWT semantics (HS256, no exp, row-existence revocation) | `sed -n '55,100p' shard_core/service/pairing.py` |
| `just set-version` behavior (commits; clean tree needed) | `sed -n '/set-version/,/^$/p' justfile` |
| Semver migration state (#118) | `gh issue view 118 --repo FreeshardBase/freeshard --json state` |
| Paperless upstream OIDC-claims PR outcome | ask Max / check paperless-ngx upstream; unverified as of 2026-07-03 |
