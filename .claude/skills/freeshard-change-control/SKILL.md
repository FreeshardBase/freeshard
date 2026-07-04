---
name: freeshard-change-control
description: "How changes get accepted into the Freeshard shard_core repo: issue triage on the Dev Board, agent pickup/handback signals, branch & PR conventions, the non-negotiables (Max-merge-only, stay on Traefik v2, no shell on shards, DO-NOT-MODIFY synced types), and release discipline (merged is NOT shipped). Use when starting work on a GitHub issue, opening a PR, deciding whether something needs an issue/spec/sign-off, or asking 'is this fix actually released?'. TRIGGER on: picking up an assigned issue, 'open a PR', 'is this shipped', 'bump the version', 'release this', 'Needs Intent', Dev Board / project board queries, Traefik version questions, edits under shard_core/data_model/backend/. SKIP when you need the mechanical release/run commands themselves (freeshard-run-and-operate), test-writing rules (freeshard-testing-and-qa), cross-repo type-sync mechanics (freeshard-ecosystem-contracts), or the history of why a past fix was rejected (freeshard-failure-archaeology)."
---

# Freeshard change control

How a change goes from idea to running-on-shards in this repo, and the rules that are
not yours to bend. Written 2026-07-03; re-verify volatile facts (last section) before
relying on them.

**Terms used throughout** (defined once):

| Term | Meaning |
|---|---|
| shard | A customer VM running the Freeshard stack (this repo's software + Traefik + Postgres + web-terminal) |
| shard_core | This repo's Python package — the per-shard control plane |
| controller | freeshard-controller (separate, **private** repo): central cloud management. Decides which shard_core image version the fleet runs |
| Max / max-tet | Owner and sole maintainer. His PR merge is the only ship gate |
| ClaydeCode | The AI agent's GitHub account. Most development happens through it |
| Dev Board | Org-level GitHub Projects v2 board where all triage lives (labels are NOT used for triage) |
| grind | Overnight loop: one fresh headless agent session per assigned issue, each in its own worktree/branch |
| core version (vN) | Controller-side host/deploy version (v17, v18, ...). Distinct from shard_core's own 0.x version |

---

## 1. The one-paragraph model

Issues are triaged by Max on the Dev Board. An issue assigned to **ClaydeCode** is the
pickup signal for agent work. The agent branches from a **freshly fetched**
`origin/main`, works in a worktree, opens a PR, and hands back by **requesting review
from max-tet**. Nothing auto-merges. Nothing merged is shipped until a version bump +
GitHub Release + controller-side rollout happen. Vague issues are never guessed at —
they get flagged for intent capture and skipped.

---

## 2. Work intake: the Dev Board

Triage lives on the org Projects v2 board **"Freeshard Dev Board"** — project **3**,
owner **FreeshardBase** (https://github.com/orgs/FreeshardBase/projects/3, org-private).
Project 2 is the separate "Freeshard Roadmap". Repo labels are irrelevant for triage:
the only custom label is `high-priority`, rarely used; the board fields are the system.

Board fields (verified 2026-07-03 via `gh project item-list 3 --owner FreeshardBase --format json`):

| Field | Values | Meaning |
|---|---|---|
| `stage` | Backlog / Refined / Done | Refined = spec is good enough to work on |
| `priority` | P0 / P1 / P2 / P3 | P0 = actively blocking users; P3 = someday |
| `needs Intent` | `yes` / null | `yes` = issue is too vague to execute; requires a spec from Max first |
| `status` | Todo / In Progress / Done | Kanban position |
| `blocked By`, `linked pull requests` | free text / links | Dependencies |

Query the board:

```bash
gh project item-list 3 --owner FreeshardBase --format json --limit 200
```

**gh traps (both verified 2026-07-03):**

- `gh issue view N --repo FreeshardBase/freeshard --comments` FAILS on this org
  ("GraphQL: Projects (classic) is being deprecated"). Use
  `gh issue view N --repo FreeshardBase/freeshard --json body,comments` instead.
- When filtering board items by repo, do NOT substring-match on
  `freeshard` — controller items leak in (the board carries items from
  `FreeshardBase/freeshard-controller` too). Match the exact URL prefix
  `https://github.com/FreeshardBase/freeshard/issues/` or use
  `.content.repository == "FreeshardBase/freeshard"`.

### Pickup and handback signals

| Signal | Meaning |
|---|---|
| Issue assigned to `ClaydeCode` | Agent should pick it up (grind loop uses exactly this) |
| PR opened + review requested from `max-tet` | Work handed back for review (e.g. PR #119 carries `reviewRequests: max-tet`) |
| `needs Intent = yes` on the board | Do NOT work it. See below |

### Needs Intent: never guess

If an issue is vague, underspecified, or flagged `needs Intent` on the board:
**stop**. Do not fill the gaps with plausible-sounding design decisions. The correct
move is to leave a comment stating what is unclear and skip the issue. Intent capture
(turning a vague issue into an approved spec) is a Max-driven process; the spec lands
as an issue comment before the issue becomes workable. Working a vague issue produces
PRs that stall for weeks — see PR #92
(https://github.com/FreeshardBase/freeshard/pull/92), stuck since 2026-05-27 on an
architectural disagreement that a spec would have settled up front.

---

## 3. Branch and PR conventions

### Always fetch first — local checkouts are routinely stale

The single most common agent mistake in this repo. Two documented instances:

- PR #113 (https://github.com/FreeshardBase/freeshard/pull/113): agent opened a
  0.39.3→0.39.4 version-bump PR that was already redundant — main had been bumped
  directly. Closed unmerged.
- As of 2026-07-03 this very checkout sat on a merged feature branch at version
  0.39.2 while `origin/main` was at 0.39.4 with a different CI workflow.

```bash
git fetch origin
git log -1 --oneline origin/main          # reason from THIS, never from local main
git ls-remote origin refs/tags/ | tail    # never infer latest release from local tags
```

Branch from `origin/main`, one branch per issue, in its own worktree for parallel
agent sessions.

### Branch names

Current agent convention: `feature/clayde/<slug>` or `fix/clayde/<slug>`
(e.g. `fix/clayde/drop-azureblob-no-check-container` → PR #119). Older agent branches
used `clayde/issue-<N>`; human branches use plain `fix/…`, `feature/…`, `chore/…`.
Match the current convention for new agent work.

### PR content

- The description must cover **all** commits on the branch, not just the last one.
- State what was tested and how; CI (`snapshot.yml`) runs ruff + pytest on every
  push/PR, and a red PR will not be reviewed.
- Behavior changes and anything touching DB migrations (`migrations/*.sql`, yoyo)
  ship with tests in the same PR. Evidence of the house norm: the #117 hotfix
  PR #119 pairs the one-line fix with `test(backup): guard rclone flags and error
  surfacing` (commit 0d42299).
- Narrative commit messages; the reasoning for a change belongs in the commit
  message, not in code comments.

### Nothing auto-merges

There is no auto-merge, no merge bot, no "trivial change" exception. Max's review and
merge click is the only ship gate. This is a deliberate design principle of the
autonomous-agent workflow, not a missing feature: the agent loop is allowed to be
aggressive precisely because a human gate sits between it and production. Do not
propose auto-merge, do not merge your own PRs, do not push to main.

---

## 4. Non-negotiables

Each of these was paid for with an incident. Do not route around them; if a task seems
to require it, stop and flag on the issue.

### 4.1 Max-merge-only (see §3)

### 4.2 Stay on Traefik v2 (v2.11) — do not resurrect v3 prep

**Decision record:** closed PR #112
(https://github.com/FreeshardBase/freeshard/pull/112) — closing comment: "we're
staying on Traefik 2 (bumping to v2.11, which is Go 1.25 and self-raises nofile — the
actual root cause)."

**Why:** the June-2026 fd-exhaustion outage (shards "up but not serving",
`accept4: too many open files`) was root-caused to the fleet's Traefik v2.6 being
built with a pre-1.19 Go (measured go1.17.10 — see freeshard-proof-and-analysis-toolkit
Recipe 1), which cannot self-raise `RLIMIT_NOFILE`. The fix was v2.11
(Go 1.25) plus a finite `readTimeout` in shard_core (PR #108,
https://github.com/FreeshardBase/freeshard/pull/108, released in 0.39.4) — NOT a
risky v3 migration under outage pressure.

**Status:** Traefik v2→v3 is a backlog item — freeshard-controller#321
(https://github.com/FreeshardBase/freeshard-controller/issues/321, private repo,
readable with ClaydeCode's gh auth), P3, `needs Intent: yes` on the Dev Board. It
lists exactly what a future migration entails (HostRegexp→Host in
`shard_core/service/traefik_dynamic_config.py`, ACME provider `azure`→`azuredns` in
`data/traefik.yml`). Until that item is Refined and picked, any `Host()`/rule-syntax
or ACME-provider change "for v3 readiness" is out of scope.

**Known wrinkle (as of 2026-07-03):** this repo's own `docker-compose.yml` (the
self-hosted/example stack) has pinned `traefik:v3.6` since 2025-12-16 (commit
e78862d), and `agents.md` says "Traefik v3". The *fleet* decision (v2.11) is enforced
controller-side in core-version compose files, not here. Treat the repo compose as an
unresolved inconsistency — do not "fix" it in either direction without an issue.

### 4.3 No shell on shards

There is no user- or app-facing shell/`docker exec` path onto a shard, by design.
Pairing is the auth boundary; an app whose first-user bootstrap requires
`docker exec` is incompatible with the platform. Diagnostics on customer shards
happen ONLY through the controller's operator-activated, time-boxed, read-only
diagnostic system with an argv-allowlisted command catalogue and append-only audit
trail (merged as freeshard-controller PR #303,
https://github.com/FreeshardBase/freeshard-controller/pull/303, private repo). Never
add an endpoint, feature, or debug pathway that executes arbitrary commands on a
shard or exposes a shell — that includes "temporary" debug endpoints in a PR.

### 4.4 `shard_core/data_model/backend/` is DO-NOT-MODIFY

Every file there is stamped `# DO NOT MODIFY - copied from freeshard-controller`.
The directory is wiped and re-copied by `just get-types` (requires
`../freeshard-controller` checked out — see the `justfile`). Hand-edits are silently
destroyed on the next sync and create type drift between repos. If a backend model is
wrong, the fix goes in freeshard-controller first, then a sync commit here (recent
example: commit 6d4b101 "chore: sync data_model types from freeshard-controller").
Full procedure: **freeshard-ecosystem-contracts**.

### 4.5 Migrations and behavior changes need tests

Any change to `migrations/` (yoyo SQL, e.g. `migrations/shard-core-0001-init.sql`)
or to observable behavior needs a test in the same PR. The test suite runs a real
PostgreSQL via pytest-docker; "hard to test" is rarely true here. How to write them:
**freeshard-testing-and-qa**.

---

## 5. Release discipline: merged is NOT shipped

A fix that is merged to main does **not** run on any shard. Shipping requires all
three steps, in order:

1. **Version bump commit** on main: `just set-version X.Y.Z` — rewrites
   `pyproject.toml` and the image tag in `docker-compose.yml`, and commits
   "set version to X.Y.Z" (see `justfile`).
2. **GitHub Release** with tag exactly `X.Y.Z`. `release.yml` first runs a
   `version-check` job that fails if tag ≠ pyproject version, then full tests, then
   builds and pushes `ghcr.io/freeshardbase/freeshard:X.Y.Z`.
3. **Controller-side rollout**: a controller core-version compose bump pins the new
   image tag for the fleet. This lives in the private freeshard-controller repo and
   is Max's/controller-side work — flag it in your PR's follow-up section; you cannot
   do it from this repo.

Steps 2 and 3 are manual maintainer actions. **Evidence this gap is real:** issue
#111 (https://github.com/FreeshardBase/freeshard/issues/111) — the fd-leak fix
(PR #108) was merged 2026-06-21 but sat in no released tag until 0.39.4 on
2026-06-24; no shard ran it in between. As of 2026-07-03 the gap is live again:
PRs #114 (https://github.com/FreeshardBase/freeshard/pull/114) and #119
(https://github.com/FreeshardBase/freeshard/pull/119) are merged after the 0.39.4
release, so the fix for release-blocker issue #117
(https://github.com/FreeshardBase/freeshard/issues/117, "v18: all backups fail")
is on main but in no released image (unless shipped since — re-verify).

**Practical consequences:**

- When asked "is X fixed?", answer in two parts: merged? (git) AND released +
  rolled out? (`gh release list`, then controller state). Never conflate them.
- Before opening a version-bump PR, fetch and check whether main was already bumped
  (the PR #113 trap, §3).
- After any infra-level minor release, expect a hotfix burst: 0.28.0→0.28.6 was
  7 tags in 3 days (2024-04-20..22, rclone rollout); 0.38.0→0.38.4 was 5 tags in a
  week (2026-04-17..23, Postgres migration rollout). Budget review capacity for it;
  don't treat a .0 as done.
- **In-flight (as of 2026-07-03):** moving shard_core to semantic versioning is
  agreed in principle — issue #118
  (https://github.com/FreeshardBase/freeshard/issues/118), P2, Stage=Backlog — but
  the mechanics (RC scheme, mapping to controller core versions vN) are unspecified.
  Do not invent semver mechanics in a PR; the current scheme (0.MINOR.PATCH, linear)
  stays until #118 is refined and executed.

Release *commands* and deploy mechanics: **freeshard-run-and-operate**.

---

## 6. Change classification: what needs what

| Change | Needs |
|---|---|
| Typo/docs-only fix, dead-link fix | Direct PR is fine; still reviewer-gated |
| Bug fix with clear repro | Issue (so triage sees it) → PR with test |
| Behavior change, new endpoint, config option | Refined issue on the board first |
| Anything vague / architectural / multi-repo | Issue + `needs Intent` spec from Max before any code |
| DB migration | Issue → PR with migration + test; see freeshard-testing-and-qa |
| Touching Traefik version, rule syntax, ACME provider | Blocked by §4.2 — needs the controller#321 backlog item refined first |
| Touching `data_model/backend/` | Change in freeshard-controller first, then sync (§4.4) |
| Version bump / release | Maintainer-driven; agents only open a bump PR when explicitly asked, after fetching (§5) |
| Anything with financial, legal, reputational, or security-posture consequences (billing/PayPal, licenses, public claims, auth boundaries, secrets handling) | Max's explicit sign-off BEFORE implementation, not just merge-time review. Propose on the issue; wait |

When in doubt between two rows, take the heavier one and say so on the issue —
a wasted comment is cheaper than a stalled PR.

---

## 7. When NOT to use this skill

| You actually need | Use |
|---|---|
| Commands to run/deploy the stack, do a release, restore a backup | **freeshard-run-and-operate** |
| Setting up the dev env, worktrees, uv, type-sync mechanics | **freeshard-build-and-env** |
| How to write/structure tests, fixtures, flaky-test playbook | **freeshard-testing-and-qa** |
| Cross-repo contracts and the `just get-types` procedure in detail | **freeshard-ecosystem-contracts** |
| Why a past fix was rejected/reverted; incident histories in depth | **freeshard-failure-archaeology** |
| Symptom→triage for a live failure | **freeshard-debugging-playbook** |
| Load-bearing design invariants (auth model, path conventions) | **freeshard-architecture-contract** |
| Config axes and env-override rules | **freeshard-config-and-flags** |

---

## Provenance and maintenance

Written 2026-07-03 by repo-archaeology against the live repo and GitHub state.
Primary sources: git history of https://github.com/FreeshardBase/freeshard;
PR #112, #113, #119; issues #108, #111, #117, #118; freeshard-controller#321,
PR controller#303 (private repo); `justfile`, `.github/workflows/{release,snapshot,test}.yml`;
Dev Board (org project 3) field dump via `gh project item-list`.

Drift-prone facts — re-verify before repeating:

| Fact (as of 2026-07-03) | Re-verify with |
|---|---|
| Latest release = 0.39.4; PRs #114/#119 merged but unreleased | `gh release list --repo FreeshardBase/freeshard --limit 3` + `git fetch && git log --oneline 0.39.4..origin/main` |
| origin/main tip = 0a40684 (merge of PR #119) | `git fetch && git log -1 --oneline origin/main` |
| Dev Board fields: stage/priority/needs Intent/status | `gh project item-list 3 --owner FreeshardBase --format json --limit 200 \| python3 -c "import json,sys; print(sorted(json.load(sys.stdin)['items'][0].keys()))"` |
| No open freeshard issues assigned to ClaydeCode | `gh issue list --repo FreeshardBase/freeshard --assignee ClaydeCode --state open` |
| Traefik v3 migration still backlogged, needs-Intent P3 | `gh issue view 321 --repo FreeshardBase/freeshard-controller --json state,title` + board item |
| Semver migration (#118) still unrefined | `gh issue view 118 --repo FreeshardBase/freeshard --json state` + board `stage` |
| Repo compose still pins `traefik:v3.6` / agents.md still says "Traefik v3" | `git show origin/main:docker-compose.yml \| grep 'image: traefik'` |
| `data_model/backend/` files still stamped DO NOT MODIFY | `head -1 shard_core/data_model/backend/shard_model.py` |
| `just set-version` still rewrites pyproject + compose tag and commits | `sed -n '/set-version/,/^$/p' justfile` |
| release.yml still gates on tag==pyproject version | `git show origin/main:.github/workflows/release.yml \| head -25` |
| Agent branch convention still `fix\|feature/clayde/<slug>` | `gh pr list --repo FreeshardBase/freeshard --state merged --limit 10 --json headRefName,author` |
| `gh issue view --comments` still broken on this org | `gh issue view 24 --repo FreeshardBase/freeshard --comments` (expect GraphQL projectCards error) |
