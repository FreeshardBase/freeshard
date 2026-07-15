---
name: freeshard-docs-and-positioning
description: Maintaining Freeshard's docs of record (agents.md, README.md, docs.freeshard.net) and writing anything user- or public-facing. TRIGGER on editing agents.md or README.md, "update the docs", "is this doc still true", contradictions between a doc and the code, the Portal/Freeshard naming question ("should I rename portal to shard?"), portal_controller.py vs freeshard_controller.py confusion, writing PR descriptions/commit messages/release notes, or any external claim about what Freeshard is or does. SKIP when the task is the mechanics of config options (use freeshard-config-and-flags), cross-repo type-sync (use freeshard-ecosystem-contracts), release *execution* (use freeshard-run-and-operate), or change gating/review policy (use freeshard-change-control).
---

# Freeshard docs and positioning

How to keep this repo's documentation truthful and how to write anything a human will read: PR descriptions, commit messages, docs pages, release notes, public copy.

Vocabulary used below: a **shard** is a personal cloud VM; **shard_core** (this repo) is the FastAPI backend running on each shard; the **controller** (repo `freeshard-controller`) is the central management service; **web-terminal** is the Vue 2 end-user UI; the project's pre-2025 name was **Portal**, and residue of that name is load-bearing (see "Naming discipline").

## When NOT to use this skill

| You are doing... | Use instead |
|---|---|
| Adding/changing a config option, env var, or flag | freeshard-config-and-flags |
| Syncing types from the controller, cross-repo contract changes | freeshard-ecosystem-contracts |
| Cutting a release, deploying, operating a shard | freeshard-run-and-operate |
| Deciding whether a change is allowed / how it gets reviewed | freeshard-change-control |
| Understanding the crypto/auth design itself (not documenting it) | freeshard-domain-reference |
| Setting up the dev environment the README describes | freeshard-build-and-env |

## Docs of record and authority order

When documents disagree, trust them in this order — and trust **code over all of them**:

| Rank | Document | Audience | Authority |
|---|---|---|---|
| 1 | The code + `git log` | — | Ground truth. Always wins. |
| 2 | `agents.md` (repo root) | Agents/engineers working on shard_core | Primary agent-facing reference: stack, architecture, commands, patterns. |
| 3 | This skill library (`.claude/skills/`) | Agents | Curated, date-stamped; defers to code. |
| 4 | `README.md` (repo root) | Humans: overview, self-hosting, dev setup | Concept sections good; the dead dev-setup mechanics were fixed by issue #128. |
| 5 | docs.freeshard.net (sibling repo `documentation/`, MkDocs Material, deployed to GitHub Pages via `.github/workflows/ci.yml`) | End users + third-party app developers | User-level truth; not an engineering reference. |
| 6 | `/home/ubuntu/projects/freeshard/agents.md` (workspace-level, one directory up) | Agents working across repos | Useful repo map + cross-repo command reference. NOT in any git repo — exists only on the dev machine; do not cite it as a versioned source. |

**Standing rule — agents.md must not rot:** when your PR changes anything agents.md describes (tech stack, architecture, key patterns, commands, file-path conventions), updating agents.md in the same PR is part of the change, not optional polish. Stale statements there cause real agent mistakes. The proof: agents.md claimed Ed25519 crypto for years while the code was RSA-4096/PSS, and the claim was believed until issue #128 checked it against `crypto.py`.

## Known-stale docs (as of 2026-07-15)

Fixing a stale doc is **in scope for any PR that touches the described area**. You do not need a separate issue to correct a doc you just proved wrong — but a pure doc-fix PR is also fine and cheap to review.

| # | Location | Stale claim | The truth | Evidence |
|---|---|---|---|---|
| 1 | `documentation/README.md` (sibling repo) | "Documentation for Portal app developers" + GitLab Pages boilerplate, badge to ptl-public.gitlab.io | Legacy scaffold README. The repo's `agents.md` is the current reference: MkDocs Material site at docs.freeshard.net. | `documentation/README.md` vs `documentation/agents.md:1-10` |
| 2 | `documentation/agents.md:61` | "Built and deployed via GitLab Pages" | Deploys via **GitHub** Pages: `.github/workflows/ci.yml` builds with `mkdocs build --strict` and deploys with `actions/upload-pages-artifact` / `actions/deploy-pages` on main. No `.gitlab-ci.yml` exists in the repo. | `documentation/.github/workflows/ci.yml` |

Before repeating ANY doc claim in new writing, verify it against code first. Re-verification one-liners for this table are in "Provenance and maintenance".

## House style: PRs, commits, issues

Conventions observable in merged history — follow them.

**Commit messages**
- Narrative. Subject line in conventional-commit-ish form (`fix(profile): ...`, `chore(deps): ...`, `perf(backup): ...`); body explains symptom, cause, and why this fix — see commit e55ce51 for the model.
- **Rationale lives in the commit message, not code comments.** Do not annotate code with "why this change exists" comments; a future reader gets the reasoning from `git log`/`git blame`. Comment code only when it is genuinely puzzling without one.

**PR descriptions**
- Must cover **all commits on the branch**, not just the last one. Reviewers read the description as the change's contract.
- Structure that has worked: `## Symptom` → `## Cause` → `## Fix` (see https://github.com/FreeshardBase/freeshard/pull/102).
- Multi-file PRs include a **"Recommended reading order"** section listing changed files in dependency order (schema/config → leaf services → API handlers → tests). Precedent: PRs https://github.com/FreeshardBase/freeshard/pull/83, /pull/90, /pull/108 all carry one.
- End agent-authored PR bodies per the harness convention (the `Co-Authored-By` / generated-with footer).

**Issues**
- Reference issues and PRs by **full URL** (https://github.com/FreeshardBase/freeshard/issues/N), never a bare `#N` — bare numbers are ambiguous across the 13 FreeshardBase repos and break when text is copied elsewhere.
- Issue/PR states are volatile: re-query with `gh` before asserting one is open/merged; never trust memory or an earlier point in the session.

## Naming discipline: the Portal residue

The project was named **Portal** until the Feb 2025 rebrand (rename commit 88e5842, "rename lots of stuff from portal to shard"). The README's top NOTE acknowledges the leftover naming publicly. What remains is **intentional-until-refactored** — much of it is external contract, not sloppiness:

| Residue | Where | Why you must NOT rename it opportunistically |
|---|---|---|
| Docker network `portal` | `docker-compose.yml:2-3`, every app compose template, `shard_core/web/internal/call_peer.py:36-39` | Every installed app's container joins this network by name. Renaming orphans running apps fleet-wide. |
| `X-Ptl-*` headers (`X-Ptl-Client-Type/Id/Name`, `X-Ptl-ID`, ...) | `shard_core/service/traefik_dynamic_config.py:92-111`, `shard_core/web/internal/auth.py:57-59`, app `app_meta.json` header templates | Apps in the store consume these headers for auth context. Wire contract. |
| `{{ portal.* }}` template variables | `shard_core/service/app_installation/util.py:91-98` (render passes `portal=` and `fs=`) | Every published app template in app-repository uses them; docs.freeshard.net documents both `portal.*` and the newer `fs.*` sets with an explicit backwards-compat note (`documentation/docs/developer_docs/includes/template_vars_portal.md`, `portal_name_info.md`). |
| `minimum_portal_size` | `shard_core/data_model/app_meta.py:125` | Field name in the published app_meta.json format (schema v1.2). Renaming = format migration, not a refactor. |
| `portal_controller.py` module | `shard_core/service/portal_controller.py` | See trap below. |
| `portal_core/` paths | Git history before 88e5842 | Use both `portal_core/` and `shard_core/` prefixes when running `git log --follow`/churn analysis across the rename. |

**Rule: no mass-renames.** A rename touching any row above is a cross-repo, fleet-affecting migration (app templates, published docs, running containers) and goes through freeshard-change-control as its own planned change. Never fold "cleaned up old Portal naming" into an unrelated PR.

**Trap — two modules, one controller:** `shard_core/service/portal_controller.py` and `shard_core/service/freeshard_controller.py` both call the SAME backend (`settings().freeshard_controller.base_url` = https://controller.freeshard.net) with different path conventions:

- `portal_controller._call_freeshard_controller` **prepends `api/`**: `url = f"{controller_base_url}/api/{path}"` (`portal_controller.py:16`). Handles profile + backup SAS URLs.
- `freeshard_controller.call_freeshard_controller` does **not** — callers pass `api/shards/self` themselves (`freeshard_controller.py:15`). Handles the shared secret.

Adding a controller call to the wrong module produces `/api/api/...` or a missing `/api/` prefix. Check which module the neighboring calls live in, and pass the path in that module's convention. (Note the naming trap that survives: the `portal_controller.py` *module* is live, but it reads `settings().freeshard_controller` — there is no `[portal_controller]` config section, since issue #128 removed the dead one.)

## External positioning and claims discipline

What Freeshard publicly is: **a personal cloud computer** — the missing category between local software, the big-cloud web, and DIY self-hosting. One person (or household) owns the machine; sovereignty over data is the point. The public anchor phrasing is `README.md:15`: "a personal cloud computer that a consumer can rent for a small monthly fee (or selfhost) and which is as simple to use as a smartphone. Its aim is to restore people's sovereignty regarding the data they consume and produce."

Rules for anything public-facing (README, docs site, release notes, blog/newsletter copy, issue comments that will be read by users):

1. **No performance, security, or privacy claim without a reproducible demonstration.** If you cannot point to a script, test, or measurement someone else can rerun, do not state the claim. Write what IS demonstrable ("auth decisions are made on your shard, not in a central service") rather than superlatives ("bulletproof", "zero-knowledge", "blazing fast").
2. **Status vocabulary is fixed:** unshipped work is "planned"; a spike/PoC is a "prototype" (e.g. the embedded OIDC provider on branch `spike/oidc-provider-poc` is a prototype — unmerged as of 2026-07-03); merged-but-not-deployed is not "shipped" (deployment gates are freeshard-change-control's territory). Never present prototype results as product capabilities.
3. **License precision.** shard_core is licensed **FSL-1.1-ALv2** (`LICENSE.md`) — Functional Source License, source-available, each version converting to Apache-2.0 two years after release (`LICENSE.md:87-91`). In external copy, describe shard_core as "source-available" / "Fair Source (FSL)" rather than unqualified "open source". The apps in the store, by contrast, ARE FOSS by policy (next rule).
4. **FOSS-only app store is public policy.** Third-party apps must carry a license from the allowlist — MIT, Apache-2.0, BSD-2/3-Clause, GPL-2.0/3.0, AGPL-3.0, LGPL-*, MPL-2.0, ISC, Unlicense, CC0-1.0 (`app-repository/.claude/skills/add-app/reference/exit-criteria.md:38`). Source-available licenses (BSL, SSPL, Elastic, O'Saasy) are a hard block regardless of technical fit — precedent: Fizzy, blocked 2026-05-18, recorded in `app-repository/blocked_apps/fizzy.md`. Rejections are documented in `app-repository/blocked_apps/` so nobody re-litigates them; when writing about the store, you may state the policy plainly and cite that directory.
5. **Third-party facts get verified, not remembered.** Anything you assert about PayPal, OVH, Azure, Traefik, an upstream app, or any external product must come from a checked source or be labeled uncertain.

## Release notes and user-visible communication

- Version history: 0.x tags on this repo (`git tag | sort -V`); as of 2026-07-03 the latest tag is 0.39.4 (2026-06-24). Minor = feature, patch = hotfix. A move to full semantic versioning is decided-in-principle but not implemented — https://github.com/FreeshardBase/freeshard/issues/118 (OPEN as of 2026-07-03).
- **Patch bursts after a minor are normal, not a scandal.** Every infra-level minor has produced a hotfix tail: 0.28.0→0.28.6 (7 releases in 3 days, 2024, rclone rollout), 0.38.0→0.38.4 (5 tags in 6 days, 2026, Postgres migration). Write the notes accordingly: state the fix plainly ("0.38.3 fixes backup validation failures on some shards"), never bury or euphemize it ("minor improvements"). Users on a broken version need to recognize their symptom in one line.
- Don't infer "latest version" from the local working tree — the checkout may sit on a stale branch (this one pins 0.39.2 in `docker-compose.yml` while 0.39.4 is tagged). Query `git fetch --tags && git tag | sort -V | tail -1` or the GitHub releases page.
- Tag order ≠ commit topology here: 0.37.5 was tagged AFTER 0.38.0 as a deliberate old-line backport (branch `origin/release/0.37.5`). When writing "what changed between X and Y", diff the tags, don't assume linearity.
- For prose style and voice of newsletters/blog posts, this skill only sets the facts-discipline; the maintainer has separate style guides outside this repo.

## Doc-impact checklist (run for every PR)

- [ ] Did I change anything `agents.md` describes (stack, architecture, patterns, commands, paths)? → update `agents.md` in this PR.
- [ ] Did I touch an area with a known-stale doc (table above)? → fix that entry in this PR and remove it from the skill's table.
- [ ] Did I add/rename/remove a `just` recipe, config option, or env var? → README dev section + `agents.md` Commands section; config specifics per freeshard-config-and-flags.
- [ ] Does the change alter what third-party app developers see (template vars, headers, app_meta format)? → the `documentation/` repo needs a matching PR (separate repo, own review).
- [ ] Does my text reference issues/PRs? → full URLs, states re-checked with `gh` now.
- [ ] Does my text make any public claim? → run it against the five claims-discipline rules above.
- [ ] PR description: covers all commits, has Symptom/Cause/Fix or equivalent, has Recommended reading order if multi-file.

## Provenance and maintenance

Written 2026-07-03; known-stale table updated 2026-07-15 after issue #128 fixed the agents.md Ed25519 claim, the README/justfile CONFIG mechanism, and the README GitLab API-doc link. Originally written against working tree at commit e55ce51 (branch `fix-profile-billing-fields`; origin/main then at 0a40684) plus sibling checkouts `documentation/` and `app-repository/` under `/home/ubuntu/projects/freeshard/`. Primary sources: repo files cited inline, `git log`/`git tag`, GitHub via `gh` (issues 41, 118; PRs 83, 90, 102, 108).

Drift-prone facts — re-verify before relying on them:

| Fact | Re-verify with |
|---|---|
| Crypto is RSA-4096/PSS, RSA_PSS_SHA512 | `grep -n "RSA_PSS\|generate_private_key" shard_core/service/signed_call.py shard_core/service/crypto.py` |
| documentation repo README/agents.md staleness | `head -5 ../documentation/README.md; grep -n "GitLab Pages" ../documentation/agents.md` |
| portal_controller `api/` prefix split | `grep -n "api/" shard_core/service/portal_controller.py shard_core/service/freeshard_controller.py` |
| Docker network still named `portal` | `grep -n "name: portal" docker-compose.yml` |
| Template render still passes `portal=` and `fs=` | `grep -n "portal=portal\|fs=fs" shard_core/service/app_installation/util.py` |
| Latest tag / semver issue state | `git fetch --tags && git tag \| sort -V \| tail -1`; `gh issue view 118 --repo FreeshardBase/freeshard --json state` |
| License still FSL-1.1-ALv2 | `head -5 LICENSE.md` |
| FOSS allowlist unchanged | `grep -n "foss" ../app-repository/.claude/skills/add-app/reference/exit-criteria.md` |
