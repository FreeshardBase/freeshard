---
name: freeshard-research-methodology
description: The discipline that turns a hunch into an accepted result in the Freeshard project — evidence bar, idea lifecycle, documented retirement, where good ideas come from, and which artifact to write when. TRIGGER on "how do I propose X", "should I spike this", "is this hypothesis proven", "why did they reject/close/abandon Y", "where do ideas get decided", writing a root-cause analysis, closing an investigation, deciding between spike branch vs issue vs PR, or handling a vague issue. SKIP when you need the mechanics of the change pipeline (gates, review, release — use freeshard-change-control), the chronicle of a specific past investigation (use freeshard-failure-archaeology), or concrete measurement recipes (use freeshard-proof-and-analysis-toolkit).
---

# Freeshard Research Methodology

How a hunch becomes an accepted result in this project — and how ideas die with a paper trail instead of silently. This is process discipline, not code knowledge.

**Terms** (used throughout, defined once):
- **shard** — a customer VM running `shard_core` (this repo: FastAPI + PostgreSQL + Docker Compose orchestration behind Traefik).
- **controller** — the central management service (repo `FreeshardBase/freeshard-controller`).
- **Max / max-tet** — owner and sole maintainer. His review+merge is the only acceptance gate. Nothing auto-merges.
- **ClaydeCode** — the AI agent GitHub account that does much of the development.
- **grind** — the overnight loop: one fresh headless agent session per GitHub issue, own git worktree, branch from main, ends in a PR for Max.
- **Dev Board** — org GitHub Project 3 (`gh project item-list 3 --owner FreeshardBase`), the real triage system. Fields: `priority` (P0–P3), `stage` (Backlog/Refined/Done), `needs Intent` (yes/null). Labels are NOT the triage system.
- **Needs Intent** — Dev Board flag meaning "issue too vague to implement; requires a spec from Max before anyone works it."

## 1. The evidence bar

Two rules separate an accepted root cause or fix from a plausible story. Both are enforced here because plausible-but-wrong analyses have burned the project before.

### Rule 1: one mechanism must explain ALL observations — including the negatives

If your explanation covers why broken things broke but not why unbroken things survived, it is not done. The negative observations are the strongest test.

**Worked example — the fd-exhaustion outage (June 2026):** new shards went silently unreachable; Traefik logged `accept4: too many open files` in a hot loop. The socket leak (readTimeout=0 on an internet-scanned IP) existed on *every* shard, old and new — so why did only new shards die? The lazy answer "old shards are fine by luck" was explicitly assigned as a hypothesis so it could be refuted, and it was killed by measurement: `docker exec traefik sh -c 'ulimit -n'` showed old shards had a much higher fd ceiling. The accepted root cause had to be **two-factor**: Traefik pinned at v2.6 (built with a pre-1.19 Go — measured go1.17.10, see freeshard-proof-and-analysis-toolkit Recipe 1 — which does not self-raise RLIMIT_NOFILE; Go 1.19+ does) × new shards on a newer Ubuntu base image whose Docker per-container nofile soft limit was 1024. One mechanism, explains the broken shards *and* the survivors. Public artifacts: fix PR https://github.com/FreeshardBase/freeshard/pull/108 (finite readTimeout), decision record in closed PR https://github.com/FreeshardBase/freeshard/pull/112.

Checklist before you claim a root cause:
- [ ] List every observation, then mark each ✓ explained / ✗ unexplained by your mechanism. Zero ✗ allowed.
- [ ] Include the negatives: systems that *should* have failed under your mechanism but didn't (or vice versa).
- [ ] If you're tempted to write "coincidence" or "luck" for any observation, promote that to a named hypothesis and design a measurement to kill it.
- [ ] Distinguish look-alike failure modes before acting — e.g. the Immich thumbnail problem had three distinct causes over two incidents (index corruption, extension-version drift, upstream regression); conflating them wastes a recovery.

### Rule 2: a fix hypothesis must predict numbers before the experiment runs

State the expected measurement *first*, then run it. If you can't say what number you expect, you don't have a hypothesis yet — you have a hope.

**Worked example A (fd-exhaustion fix):** prediction — a Traefik v2.11 container (Go 1.25) will show `ulimit -n` self-raised to the hard limit (order 64k, per the investigation records), while v2.6 (pre-1.19 Go) stays at the 1024 soft limit. The Go version per Traefik tag was checked in the tag's `go.mod` before the upgrade was chosen. The measurement matched; the upgrade shipped as v2.11, and the "obvious" v3 migration was avoided (see §5).

**Worked example B (pricing rounding):** Python `round()` is banker's rounding, JS `Math.round()` is half-up — under the new VAT-bearing formula they diverged by 1 cent on half-cent results, so the UI label could disagree with the PayPal charge. The fix (half-up `int(x*100 + 0.5)` in the backend) came with a prediction: **zero divergences across the entire size×disk pricing matrix**, and expected test values recomputed from the real function rather than hand-derived. Public artifact: https://github.com/FreeshardBase/freeshard-controller/pull/298 (merged 2026-06-09).

Corollary: pinned test values are recomputed from the canonical implementation, never invented — a hand-derived expected value just encodes your possibly-wrong mental model twice.

## 2. The idea lifecycle

Every idea in this project moves through the same pipeline. Skipping a stage is how work gets orphaned (see PR #86 in §4).

| Stage | Artifact | Rule | Real example |
|---|---|---|---|
| 1. Hunch | nothing, or an issue comment | Cheap to hold, cheap to drop | "personal agent as a native shard app" — deliberately marinating, no code |
| 2. Spike (optional) | `spike/*` branch | Spikes are UNMERGED reference material; production impl starts on a fresh branch | `spike/oidc-provider-poc` (4 commits, local worktree only, not on origin, as of 2026-07-03) |
| 3. Decision | issue comment, PR comment, or maintainer sync | May use the solution-neutral-brief method (below); decision gets written down where the next person will look | Embedded OIDC over Authelia, 2026-06-12 |
| 4. Issue + intent | GitHub issue; Dev Board card | Vague issues get the `needs Intent` flag and are SKIPPED by implementers, never guessed at | #26, #81, #109, #110, #115 all flagged as of 2026-07-03 |
| 5. Implementation | grind worktree, branch from main | One fresh agent session per issue | most of recent history |
| 6. PR | pull request | Narrative description; reviewer = max-tet | — |
| 7. Acceptance | Max's review + merge | The ONLY acceptance. See freeshard-change-control | — |
| 8. Release | version bump + tag + GitHub Release | Merged ≠ shipped (issue #111 is the cautionary tale). See freeshard-change-control | — |

### The solution-neutral-brief method (stage 3)

When a design decision is contested or suspiciously comfortable, validate it by independent re-derivation:

1. Write a requirements brief with **zero solution hints** — constraints only (for the identity decision: restart-free config, footprint on a 1 GB VM, passwordless onboarding, no-email constraint). No product names, no architecture sketch.
2. Hand it to a **fresh agent session** with no context of the debate.
3. Compare what it independently derives against your candidate.

This is how the identity decision was made (2026-06-12): after weeks of Authelia spec churn (issue https://github.com/FreeshardBase/freeshard/issues/36, PR https://github.com/FreeshardBase/freeshard/pull/86), a fresh session given only the requirements re-derived Authelia as a candidate but recommended an **embedded OIDC provider inside shard_core** (Authlib). A same-day PoC (~740 LoC, 13 integration tests, zero-click Immich login) landed on `spike/oidc-provider-poc`. The counter-risks (crypto unknown-unknowns in a self-built IdP, AI-scannable public repo) were recorded, not ignored. Full campaign state: see freeshard-oidc-identity-campaign.

If the fresh session derives something different from your candidate, that is signal, not noise — investigate before overriding.

### Intent capture in practice (stage 4)

The issue thread IS the spec medium. Pattern visible in issue #36: agent posts a preliminary plan with explicit open questions → Max answers in a comment → agent posts "Plan updated" naming what changed → repeat until no open questions → implement. If an issue is too vague even to draft questions, it gets `needs Intent` on the Dev Board and nobody touches it. Check the flag before starting any issue:

```bash
gh project item-list 3 --owner FreeshardBase --format json --limit 200 \
  | jq -r '.items[] | select(.content.number==<N> and (.content.url // "" | startswith("https://github.com/FreeshardBase/freeshard/"))) | .["needs Intent"]'
```

(The URL prefix check matters — substring matching leaks controller-repo items with the same numbers.)

## 3. Retirement is documented, not silent

Dead ideas get a tombstone that states the reason and, where one exists, the successor direction. Three established patterns:

| Pattern | Where | Example |
|---|---|---|
| Block record file | `blocked_apps/<name>.md` in `FreeshardBase/app-repository` | `blocked_apps/fizzy.md`: block date, exit code, reason (source-available O'Saasy license fails the FOSS gate), plus research notes so a recheck doesn't restart from zero |
| Decision comment on the closed PR | the PR thread | https://github.com/FreeshardBase/freeshard/pull/112 closed with: staying on Traefik v2 (v2.11 = Go 1.25 self-raises nofile = the actual root cause), v3 migration folded into a needs-Intent backlog ticket |
| Bulk-close with reasons | issue closing comments | 2026-06-29 backlog cleanup closed #18, #25, #33, #36, #37, #71, #72, #111 within minutes, each with a comment stating why (e.g. #36: "per-shard single-tenant isolation rather than multi-instance YAML-backend sharding") |

Rules when YOU retire something:
- Never close silently. One comment: why now, and what (if anything) supersedes it.
- Never delete the evidence. Abandoned branches stay: `feature/sqlite` (the abandoned SQLite route) and `copilot/migrate-database-to-postgres` + `issue/25-replace-tinydb-with-postgres` (the two failed TinyDB→PostgreSQL attempts, PRs #29 and #34) still document the dead ends that made merged PR #56 possible.
- Check for orphans your retirement creates. Counter-example to avoid: PR https://github.com/FreeshardBase/freeshard/pull/86 (Authelia core IAM) was still open when its driving issue #36 was closed and the embedded-OIDC decision superseded it — as of 2026-07-03 it dangles with no decision comment. Don't reproduce that state; close or annotate dependent PRs when the direction dies.
- A settled investigation MUST land in freeshard-failure-archaeology (see §6).

## 4. Where good ideas historically came from

Know the sources; watch them deliberately.

| Source | Mechanism | Evidence |
|---|---|---|
| Production incidents | Incident → runbook → generalizing feature/issue | The agentic shard-diagnostics feature (controller PR https://github.com/FreeshardBase/freeshard-controller/pull/303, merged 2026-06-16) grew out of real customer-shard troubleshooting and then proved itself root-causing the fd-exhaustion and Immich incidents. The July 2026 Immich incident directly spawned issues https://github.com/FreeshardBase/freeshard/issues/120 (make OOM kills visible) and https://github.com/FreeshardBase/freeshard/issues/121 (no-interruption window for migrations) |
| Weekly maintainer syncs | Max + collaborator (Aaron) discuss; decisions and open questions get minuted; issues filed after | The semver-for-shard-core decision → https://github.com/FreeshardBase/freeshard/issues/118; the flagship-apps curation strategy → https://github.com/FreeshardBase/freeshard/issues/110 |
| Adversarial review of first designs | Build v1, attack it next day, keep only what survives | The first agentic dev-loop (in-container agent, derived-phase state machine, review-packet pipeline) was retired the DAY after it went live as overbuilt; the surviving design is "dumb loop, smart per-issue agent" — dispatcher has no intelligence, GitHub is the only state store |
| Solution-neutral re-derivation | §2, stage 3 | The embedded-OIDC decision |
| Upstream/ecosystem watching | Track competitor products, upstream releases, license changes | Recheck procedures in `blocked_apps/`; the personal-agent product analysis names specific ecosystem projects as build-vs-embed candidates |

## 5. Anti-patterns — each one has a story

| Anti-pattern | The story | The rule |
|---|---|---|
| Shipping the obvious-but-risky fix | The "obvious" fd-exhaustion fix was migrating Traefik v2→v3 (new major, new rule syntax, unknown blast radius). Investigation showed the root cause was the *Go toolchain version* of the pinned build, so v2.11 (Go 1.25) fixed it with near-zero migration risk. v3 prep work was dropped (PR #112) | Ask: what is the *minimal* change that addresses the verified mechanism? Bigger migrations need their own justification, not a bug to hide behind |
| Guessing at vague issues | The whole `needs Intent` machinery exists because a guessed implementation wastes a full agent session and a review slot, and anchors later discussion to the wrong design | If intent is unclear: flag, skip, move on. Never "probably they meant..." |
| Trusting a mocked test where the real system differs | The grind loop's unit tests were green; its first *supervised real run* immediately surfaced infra bugs the mocks had hidden (expired auth token, git push auth, GitHub combined-status API returning `total_count=0` on Actions-only repos) | Mocks prove your code matches your model of the boundary, not the boundary. First run of any new automation is supervised. See freeshard-testing-and-qa for what counts as evidence |
| Building elaborate orchestration before proving the dumb version fails | The v1 dev-loop had a state machine, in-container execution, and a planned review-packet pipeline. The dumb replacement (flat loop, fresh session per issue, GitHub as state) shipped the next day and is what actually runs | Build the dumb version first. Add machinery only when the dumb version demonstrably fails, and keep the failure evidence |
| Letting a disagreement stall silently | PR https://github.com/FreeshardBase/freeshard/pull/92: maintainer requested a simpler approach; agent replied with a technical constraint (Traefik's errors middleware discards the upstream body); no movement since 2026-05-27 | When review reaches an architectural impasse, both positions belong in the thread (they are, here) — then the item needs an explicit decision or a `needs Intent`-style flag, not more commits and not silence |

## 6. Which artifact do I write?

| Situation | Artifact | Not |
|---|---|---|
| Exploring feasibility, code is throwaway | `spike/<slug>` branch; never merged; production work restarts on a fresh branch | a PR |
| Root-cause found, fix known | Issue (symptom, mechanism, evidence incl. negatives) → PR referencing it | a PR with the analysis buried in commit messages |
| Root-cause found, fix deferred/rejected | Issue comment or closing comment stating mechanism + why deferred | silence |
| Design decision made | Comment on the driving issue/PR; if it retires other work, decision comments there too | only a private note |
| Recurring operational knowledge (how to recover X) | Runbook / docs change — see freeshard-docs-and-positioning | re-deriving it next incident |
| Investigation settled (root cause accepted, fix shipped or consciously rejected) | **Mandatory**: entry in freeshard-failure-archaeology (symptom → root cause → evidence → status), plus a symptom row in freeshard-debugging-playbook if it can recur | leaving it only in a PR thread |
| Process/methodology lesson | Update to the relevant skill in `.claude/skills/` | a one-off comment nobody will find |

## 7. When NOT to use this skill

- You need the **change pipeline mechanics** — classification, gates, review expectations, release procedure, merged-vs-shipped: use **freeshard-change-control**.
- You're **debugging a live symptom** and want the known-failure-mode triage table: use **freeshard-debugging-playbook**.
- You want the **full chronicle of a past investigation** (fd-exhaustion, Immich, Content-Type 422s, ...): use **freeshard-failure-archaeology**.
- You need a **measurement recipe** (how to actually get the numbers Rule 2 demands): use **freeshard-proof-and-analysis-toolkit** and **freeshard-diagnostics-and-tooling**.
- You're working the **OIDC identity effort** specifically: use **freeshard-oidc-identity-campaign**.
- You're looking for **open research problems** rather than the discipline for settling them: use **freeshard-research-frontier**.

## Provenance and maintenance

Written 2026-07-03. Primary public sources: this repo's git history and branch set; GitHub issues/PRs cited inline (freeshard #36, #86, #89–#94, #106, #108, #111, #112, #117–#121, #24/#88, #29/#34/#56, #92; controller #298, #303); `FreeshardBase/app-repository` `blocked_apps/`; the FreeshardBase Dev Board (org project 3). Some narrative details (the solution-neutral-brief walkthrough, grind-loop first-run bugs, weekly-sync origins) come from maintainer records without a public artifact; they are stated as history, not cited.

Drift-prone facts — re-verify before relying on them:

| Fact (as of 2026-07-03) | Re-verify with |
|---|---|
| `spike/oidc-provider-poc` is local-only, unmerged; production OIDC impl not started | `git branch -a \| grep -i oidc && git log --oneline spike/oidc-provider-poc \| head -5` |
| PR #86 (Authelia) still open/orphaned | `gh pr view 86 --repo FreeshardBase/freeshard --json state` |
| PR #92 still stalled at CHANGES_REQUESTED | `gh pr view 92 --repo FreeshardBase/freeshard --json state,reviewDecision` |
| Dev Board = project 3; fields `priority`, `stage`, `needs Intent` | `gh project item-list 3 --owner FreeshardBase --format json --limit 5 \| jq '.items[0] \| keys'` |
| Needs-Intent-flagged issue set (#26, #81, #109, #110, #115, ...) | the §2 stage-4 jq query, per issue |
| `blocked_apps/` pattern exists with fizzy.md | `gh api repos/FreeshardBase/app-repository/contents/blocked_apps --jq '.[].name'` |
| Traefik-stays-on-v2 decision unrevisited | `gh pr view 112 --repo FreeshardBase/freeshard --json comments --jq '.comments[].body'` and search issues for "traefik v3" |
| Semver migration (#118) still open/unspecified | `gh issue view 118 --repo FreeshardBase/freeshard --json state` |
| Abandoned DB-migration branches still present as reference | `git branch -r \| grep -E 'sqlite\|postgres'` |
| Bulk-close comments intact on #36 etc. | `gh issue view 36 --repo FreeshardBase/freeshard --json comments --jq '.comments[-1]'` (NOT `--comments`, which errors on this org) |
