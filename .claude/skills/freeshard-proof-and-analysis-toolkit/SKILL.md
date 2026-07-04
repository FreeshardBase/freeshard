---
name: freeshard-proof-and-analysis-toolkit
description: First-principles analysis recipes for the Freeshard repos — how to PROVE a root cause instead of pattern-matching to the first plausible fix. Use when only a subset of shards/requests fails, when two components disagree about the same bytes, when a formula is duplicated across languages, when adding per-request DB/IO work, when a container "looks OOM-killed", when a guard/sentinel exists and you must say what it protects, when optimizing cloud cost, or before running any discriminating experiment. TRIGGER on "root cause", "why does only X fail", "prove the mechanism behind this failure class (fd exhaustion, pool exhaustion, proxy write rejection, kill loops)", "rounding mismatch", "prices disagree", "Azure cost", "migration never ran", "prove it". If you only have the raw symptom string (an EMFILE loop, a 422, an OOM-looking restart loop), load freeshard-debugging-playbook first. SKIP when you need the symptom→triage lookup table for a KNOWN failure mode (use freeshard-debugging-playbook), the history of a specific past investigation (use freeshard-failure-archaeology), or the evidence-bar/idea-lifecycle discipline itself (use freeshard-research-methodology).
---

# Freeshard proof and analysis toolkit

Eight recipes for turning "probably X" into "proven X", each with a worked example from this project's real history. The house rule they encode: **prove it, don't just install it** — a fix shipped on an unproven root cause here has repeatedly either done nothing (reload-vs-restart, controller PR [#312](https://github.com/FreeshardBase/freeshard-controller/pull/312)) or broken production (rclone flag regression, [#117](https://github.com/FreeshardBase/freeshard/issues/117)).

Terms used throughout, defined once:

| Term | Meaning |
|---|---|
| shard | A customer VM running the shard stack (Traefik + shard_core + web-terminal + Postgres) |
| shard_core | This repo — the FastAPI service on each shard that manages apps, auth, backup |
| controller | freeshard-controller — the central service that provisions shards, deploys core versions, bills |
| core version (vN) | A versioned compose stack + host scripts the controller pushes to shard hosts (`freeshard-controller-backend/data/core-versions/vN/`) |
| forwardAuth | Traefik middleware that calls shard_core `/internal/auth` on **every** request to a private app |

Reading issue threads for evidence — two gh traps: `gh issue view N --comments` 500s on this org (deprecated Projects classic); use `gh issue view N --repo FreeshardBase/freeshard --json body,comments`. And the richest evidence is usually in PR/issue **bodies and comment corrections**, not commit messages.

## Recipe index

| Your situation | Recipe |
|---|---|
| Only a subset (new shards, some requests, one region) fails; the rest is "fine" | 1. Two-factor root-cause proof |
| Component A and component B disagree about the same request/bytes | 2. Wire-level ground truth |
| The same formula/logic is hand-duplicated across languages or repos | 3. Exhaustive-domain verification |
| You're adding per-request DB/IO work, or a burst caused mass failures | 4. Resource arithmetic |
| A container dies repeatedly and "it's OOM" is the leading theory | 5. Kill-signal forensics |
| A guard/sentinel/check exists and you're relying on it | 6. Delivery-vs-execution guard analysis |
| Cloud spend is high and you're about to optimize storage/compute | 7. Cost-meter attribution |
| You're about to run ANY discriminating experiment | 8. Hypothesis-predicts-numbers (run this inside every other recipe) |

---

## Recipe 1 — Two-factor root-cause proof (when only a subset fails)

**When:** a failure hits some shards/requests/environments and not others, and the tempting explanation is one-factor ("new shards are broken") or no-factor ("the old ones are just lucky").

**Steps:**
1. Write down the exact partition: which population fails, which doesn't. Refuse to proceed until the partition is crisp.
2. Enumerate every variable that differs across the partition (image version, base OS, ulimits, config, age, provider region). Get each value by **measurement on both sides**, not from docs.
3. A subset-only failure usually needs an **interaction of ≥2 factors** — one factor supplies the defect, the other the threshold. Find the pair whose combination predicts the partition exactly.
4. Explicitly DISPROVE the lazy hypothesis ("survivors are lucky / it's random"): show the survivors' measured values put them on the safe side of the threshold.
5. Only then choose a fix — and prefer the one that removes the defect, not the one that moves the threshold.

**Worked example — the June 2026 fd-exhaustion outage.** Shards went silently unreachable; traefik logged `accept4: too many open files` (EMFILE) in a hot loop; that log spam itself grew 38 GB in 3 days and filled root disk, bricking upgrades (controller [#306](https://github.com/FreeshardBase/freeshard-controller/issues/306)). Only **newer** shards died. The partition: new shards ran on the Ubuntu 26.04 base image (OVH had rotated out 25.04) with a per-container `nofile` soft limit of **1024**; old shards had a higher ceiling. The defect was shared by *all* shards: traefik entrypoints had `readTimeout=0`, so internet scanners' abandoned connections each leaked one fd forever ([freeshard#108](https://github.com/FreeshardBase/freeshard/issues/108)). The interaction: leak × low ceiling = EMFILE on new shards only. "Old shards fine = luck" was disproven by measuring `docker exec traefik sh -c 'ulimit -n'` on both populations (1024 confirmed on failing shard 333 — controller PR [#322](https://github.com/FreeshardBase/freeshard-controller/pull/322)) and by Go-toolchain archaeology: a Go binary ≥1.19 self-raises RLIMIT_NOFILE to the hard limit at startup; the pinned traefik v2.6 predates that.

```bash
# the threshold, on a live shard (via diagnostics; needs an open diagnostic):
docker exec traefik sh -c 'ulimit -n'
# toolchain archaeology, lower bound from go.mod at the tag:
gh api 'repos/traefik/traefik/contents/go.mod?ref=v2.6' --jq '.content' | base64 -d | grep '^go '   # -> go 1.17
# definitive: what the shipped binary was actually built with:
docker run --rm traefik:v2.6 version    # -> Go version: go1.17.10  (verified 2026-07-03)
docker run --rm traefik:v2.11 version   # -> Go version: go1.25.x
```

(PR #322's body says "v2.6 is Go 1.16"; the measured current v2.6 image is go1.17.10 — either way <1.19, so the conclusion stands. Trust `version` output over go.mod over prose.)

The proof changed the fix: instead of the "obvious" risky traefik v2→v3 migration, the fleet got traefik **v2.11** (Go 1.25, self-raises ~1024→hard limit; controller PRs [#320](https://github.com/FreeshardBase/freeshard-controller/pull/320), [#322](https://github.com/FreeshardBase/freeshard-controller/pull/322)) plus finite `readTimeout` in shard_core ([freeshard#108](https://github.com/FreeshardBase/freeshard/issues/108), shipped 0.39.4) plus a `nofile` ulimit and log rotation as defense-in-depth (controller PRs [#311](https://github.com/FreeshardBase/freeshard-controller/pull/311), [#312](https://github.com/FreeshardBase/freeshard-controller/pull/312)). The stay-on-v2 decision is recorded in the closing comment of [freeshard PR #112](https://github.com/FreeshardBase/freeshard/pull/112) — do not resurrect v3-prep changes.

**Failure mode of skipping it:** you ship the one-factor fix (a v3 migration, or just log rotation as [#306](https://github.com/FreeshardBase/freeshard-controller/issues/306) first proposed) — the leak persists, the outage recurs on the next threshold change, and you've taken migration risk for nothing. Note also [freeshard#111](https://github.com/FreeshardBase/freeshard/issues/111): the readTimeout fix was merged but sat in no released tag — merged-is-not-shipped (see freeshard-change-control).

---

## Recipe 2 — Wire-level ground truth (when two components disagree)

**When:** component A insists it sends X, component B insists it receives Y, and you're on your second hour of reading both codebases. Also whenever a proxy/middleware sits between them — on shards, Traefik **swallows upstream error bodies** (controller [#266](https://github.com/FreeshardBase/freeshard-controller/issues/266)), so the error you see is not the error that was sent.

**Steps:**
1. Stop reading code. Capture the actual bytes on the wire at the hop closest to the disagreement — the plaintext internal hop (Traefik→backend) is capturable without TLS games.
2. Get the **full** error payload, not the proxied summary: `curl` the backend container directly, or tcpdump inside its network namespace.
3. Compare captured bytes against each side's claim. One of them is wrong; now you know which.
4. Treat any intermediate log line as a *claim*, not evidence — logs render bytes through a serializer that can lie about structure.

```bash
# tcpdump inside another container's netns, no tools installed on it:
docker run --rm --net container:<backend-container> nicolaka/netshoot \
  tcpdump -i any -A -s0 'tcp port 80'
```

**Worked example — the Content-Type bug (May 2026).** Every proxied write from shards to the controller returned 422; reads were fine. Static analysis of both repos concluded "the code as written should NOT return 422" and produced a wrong leading hypothesis (version skew) — see controller [#267](https://github.com/FreeshardBase/freeshard-controller/issues/267)'s body. The tcpdump capture of the Traefik→backend hop got the real 422 detail: `model_attributes_type`, with the payload rendered as a string. First reading of that capture spawned a **red herring**: "the body is double-JSON-encoded" — two full comments in #267 chased re-encoding through shard_core, the TS client, and axios before the correction landed. The actual cause: `shard_core/web/internal/call_backend.py` forwarded the body but passed no `headers=`, and `requests` sets no Content-Type for bytes `data`; the controller's FastAPI bump 0.115→0.136 flipped `strict_content_type=True`, which skips JSON-parsing a body without a JSON Content-Type — pydantic then validates raw bytes and the 422's `input` field *renders* them as a string. Fix: forward Content-Type (only) — [freeshard#93](https://github.com/FreeshardBase/freeshard/issues/93) / PR [#94](https://github.com/FreeshardBase/freeshard/pull/94), commit 167d779, now `shard_core/web/internal/call_backend.py:34-40`.

Two durable lessons from the red herring: (a) an error message's *rendering* of the input is not the input's wire encoding — the capture disproved double-encoding as fast as it suggested it, once re-read against the fix hypothesis; (b) prove the innocent party innocent: a direct request with the header present returned 200/204, isolating the defect to the sending side.

**Failure mode of skipping it:** codebase archaeology proves both sides "correct" forever (both *were* internally consistent here), while the actual defect lives in an unstated default between them. #267 shows the full cost: three hypotheses, two of them wrong, until bytes were captured.

---

## Recipe 3 — Exhaustive-domain verification (duplicated formulas)

**When:** the same computation is hand-duplicated across languages/repos and must agree bit-identically. In this ecosystem that is the **pricing formula**, duplicated on purpose: controller `freeshard-controller-backend/freeshard_controller/service/pricing.py` (canonical) + its tests, web-terminal `src/lib/pricing.js` + its spec, landing-page `src/components/Pricing.astro` (see the sibling-PR blocks in controller PR [#298](https://github.com/FreeshardBase/freeshard-controller/pull/298) and web-terminal PR [#30](https://github.com/FreeshardBase/web-terminal/pull/30)).

**Steps:**
1. Enumerate the **entire** input domain the product actually offers (every VM size × every disk-size option in the UI picker). It is small — tens of combinations. Never sample.
2. Run both implementations over the full domain and diff outputs **in integer cents** (never floats-to-2-decimals).
3. Pin a handful of the results as test values in each repo, *recomputed from the real function*, never hand-derived (#298 did exactly this: "16 expected-cent values recomputed from the real function").
4. Any change to the formula changes **all** copies in one lockstep set of sibling PRs.

```bash
python3 - <<'EOF'
vm = {'xs': 5.50, 's': 11.00, 'm': 19.80, 'l': 51.00, 'xl': 102.00}  # verify against pricing.py first
for size, base in vm.items():
    for gb in DISK_OPTIONS_FROM_UI:   # enumerate exactly what the picker offers — all of it
        eur = (base + gb * 0.04) * 1.5 * 1.19
        print(size, gb, int(eur * 100 + 0.5))
EOF
# then the same loop in node with Math.round(total*100), and `diff` the two outputs.
```

**Worked example — the rounding divergence (June 2026).** When the 19% VAT factor landed (controller PR [#298](https://github.com/FreeshardBase/freeshard-controller/pull/298)), Python's `round()` (banker's rounding) and JS's `Math.round()` (half-up) — which had agreed under the old formula — began diverging by 1 cent on half-cent results (e.g. S + 250 GB). Consequence if unfixed: the UI price label disagrees with the PayPal charge. Sampling would likely have missed it — the divergent cases are a thin slice of the domain; only enumerating every size×disk combination surfaced them. Fix: backend switched to half-up `int(eur * 100 + 0.5)`, bit-identical to `Math.round` for positive values — the comment in `pricing.py` records this. **Never use Python `round()` in pricing code.**

**Failure mode of skipping it:** a green test suite on both sides (each internally consistent), pinned test values that encode the divergence as "expected", and a customer charged a different amount than displayed — a trust/legal problem, not a rounding problem.

---

## Recipe 4 — Resource arithmetic (before shipping per-request work)

**When:** adding any per-request DB query, connection, subprocess, or lock on a hot path — especially anything reachable from Traefik forwardAuth, which fires on **every** request to a private app. Also when a burst caused simultaneous mass failures and you need the mechanism.

**Steps:**
1. Write the arithmetic down: peak parallel requests × resources acquired per request vs. pool/limit size. A SPA loading is a legitimate burst of ~30 parallel requests, not an attack.
2. Compute the failure timeline the numbers predict (queue-wait timeouts stack — see the worked example's 45 s) and check it against the observed symptom. If the numbers reproduce the symptom, the mechanism is proven.
3. Fix the *rate*, not just the *capacity*: a bigger pool moves the threshold; caching removes the per-request work. Ship both, but know which one is the fix.
4. New per-request state needs signal-driven invalidation, not TTLs — follow the existing pattern in `shard_core/web/internal/auth.py` (caches invalidated by `on_identity_update` / `on_apps_update`).

**Worked example — DB pool exhaustion, [freeshard#89](https://github.com/FreeshardBase/freeshard/issues/89) (May 2026).** Actual Budget's frontend fetched ~30 migration files in parallel; all uncached ones 500'd simultaneously at ~45 s, with **zero** log entries in the app container. The issue body shows the arithmetic that proved it: pool opened with psycopg_pool defaults → `max_size=4`; each forwardAuth call serially acquired 2–3 connections (`_find_app`, `_get_identity`, plus `docker_start_app`); 30-parallel burst ⇒ pool exhausted within 2–3 in-flight auths ⇒ remaining `getconn()` block until the default 30 s pool timeout ⇒ `PoolTimeout` ⇒ 500. Predicted timeline: 30 s timeout + auth round-trip + forwardAuth overhead ≈ the observed ~45 s. Fix (PR [#90](https://github.com/FreeshardBase/freeshard/pull/90), commits 1e0e7c1 + 868e690): pool `max_size=20, timeout=10` (`shard_core/database/connection.py:28-29`) **and** in-process identity/app caches so steady-state auth is zero-DB-query. The cache-invalidation bug was caught and patched in a same-PR follow-up commit — capacity alone had been the first draft.

**Failure mode of skipping it:** the symptom is opaque by construction (proxy 500s, upstream logs empty — only shard_core logs show `PoolTimeout`), so without the arithmetic you blame the app, the network, or Traefik. And a pool bump alone leaves 2–3 queries per request on a path hit by every request fleet-wide — the next-larger burst recreates the outage.

---

## Recipe 5 — Kill-signal forensics (before scaling resources)

**When:** a container dies repeatedly and someone says OOM. RAM upgrades cost real money per month per shard; a wrong OOM diagnosis also masks a data-corruption bug that will follow the app to the bigger VM.

**Steps:**
1. Read the exit state before theorizing:
   ```bash
   docker inspect <container> \
     --format '{{.State.ExitCode}} oom={{.State.OOMKilled}} restarts={{.RestartCount}} started={{.State.StartedAt}}'
   ```
   Exit code = 128 + signal: **137 = SIGKILL** (external: kernel OOM killer or docker), **134 = SIGABRT** (the process aborted *itself* — assertion, PANIC, corrupt extension).
2. Corroborate externally: kernel OOM kills land in the kernel ring buffer (`journalctl -k | grep -i oom`), never in the app's own logs. Clean app logs + climbing restart count = external kill *signature*, but confirm the signal.
3. Discriminate: SIGKILL+`OOMKilled=true` → genuinely out of memory → sizing/swap territory. SIGABRT → the app is broken internally → more RAM predicts **no change**.
4. If you must test the OOM hypothesis, resizing RAM upward is a clean falsification experiment — write the prediction first (Recipe 8): OOM predicts the crash stops; SIGABRT predicts nothing changes.

**Worked example — two Immich incidents that look identical and aren't.** (A) A size-S shard (3.8 GB RAM, swap=0): `immich_server` at 18 restarts, each boot clean then killed from outside; sibling containers untouched — classic per-app OOM kill; the user just saw "Immich keeps stopping" ([freeshard#120](https://github.com/FreeshardBase/freeshard/issues/120)). (B) July 2026, shard daf3qd: the app compose pinned Immich v2.7.5 but froze the DB image at VectorChord 0.3.0 when v2.7.5 needs 0.4.3 — uploads aborted, hard 502 crash-loop, and the platform's restart policy kept killing the minutes-long startup migration ([app-repository#29](https://github.com/FreeshardBase/app-repository/issues/29), [freeshard#121](https://github.com/FreeshardBase/freeshard/issues/121)). B *looked* like OOM; the crashes were SIGABRT — the DB extension aborting — and during the investigation the shard was resized upward as a falsification test and the crash persisted, exactly as the SIGABRT hypothesis predicted (the resize experiment is from the incident investigation; it is not recorded in the public threads). Recovery was DB surgery (`ALTER EXTENSION vchord UPDATE` + `REINDEX`), not RAM. Note the tooling gap this exposed: the read-only diagnostics probes could show restarts but not `ExitCode`/`OOMKilled`, forcing circumstantial reasoning — controller [#327](https://github.com/FreeshardBase/freeshard-controller/issues/327) tracks it; until fixed, get the inspect fields via a higher-level diagnostic or host access.

**Failure mode of skipping it:** you double the customer's monthly price and the app still crashes — now with a confused diagnosis ("it can't be memory, we doubled it") and a corrupted vector index that no amount of RAM will reindex.

---

## Recipe 6 — Delivery-vs-execution guard analysis

**When:** a guard exists (sentinel file, "already applied" flag, dedup check, idempotency marker) and correctness depends on it. The question to ask, verbatim: **what does this guard actually protect against — and what does it silently NOT protect against?**

**Steps:**
1. Name the guarded operation's two halves: *delivery* (does the work arrive where it must run?) and *execution* (does it run exactly once?). Most guards cover exactly one half.
2. Enumerate the paths that bypass the unguarded half. For fleet mechanisms the classics are: freshly provisioned nodes (never received old deliveries) and version-skipping upgrades (intermediate deliveries never made).
3. Prefer designs that make the guard unnecessary: idempotent reconcilers run on **every** converge beat run-once sentinels, because "did it ever run?" stops being a question.
4. When auditing, don't check "is the sentinel present" — check "is the *effect* present" on a node that took the bypass path.

**Worked example — cumulative core-host migrations (controller [#307](https://github.com/FreeshardBase/freeshard-controller/issues/307), June 2026).** Per-shard host migrations were version-scoped: `_put_core_files(version)` uploaded only that version's scripts, and the `.migrations_applied` sentinel prevented re-running. The sentinel guarded **execution**; nothing guarded **delivery**. Consequence: shards provisioned fresh at vN never ran earlier versions' migrations, and a v15→v17 upgrade silently skipped v16's — "bugs appear fixed in vN but are absent on real shards." This is precisely how the fd-exhaustion `nofile` migration turned out to have never run on a broken shard. Fix arc: deliver the cumulative union of all versions' scripts with globally-unique `vN-NN-description.sh` names and numeric ordering (PR [#308](https://github.com/FreeshardBase/freeshard-controller/pull/308)), then go further and replace run-once sentinels with idempotent reconcilers executed on every converge (PR [#323](https://github.com/FreeshardBase/freeshard-controller/pull/323)). Side-constraint that now exists: under the cumulative collector a duplicate script basename across versions fails collection — new core versions may rely on earlier reconcilers instead of copying them (see PR [#322](https://github.com/FreeshardBase/freeshard-controller/pull/322)'s notes). Same family, same repo: `systemctl reload docker` "applied" a daemon.json change that SIGHUP doesn't actually reload (log-opts, default-ulimits) — the guard-shaped step succeeded while the effect never happened; only a full `systemctl restart docker` in v17 made it real (PRs [#309](https://github.com/FreeshardBase/freeshard-controller/pull/309), [#312](https://github.com/FreeshardBase/freeshard-controller/pull/312)).

**Failure mode of skipping it:** the guard gives you *confidence* exactly where you have no *coverage*. You mark the fleet "migrated" and stop looking — the un-delivered nodes fail months later with a bug you believe you already fixed.

---

## Recipe 7 — Cost-meter attribution (before optimizing spend)

**When:** a cloud bill line is high and the instinct is "store less / compress / delete". Read the **meter breakdown** first — cloud providers bill operations, not just bytes, and ops can dominate.

**Steps:**
1. Pull the per-meter cost breakdown for the account/service — read-only `az costmanagement query` calls against the Freeshard subscription (the api-azure skill wraps these, if your session has it; otherwise use the `az` CLI directly with reader credentials). Identify the top meter by euros, not by intuition.
2. Attribute the meter to a code path: which process issues that operation class, how many times, on what schedule? Multiply it out — ops/night × shards × 30 must reproduce the meter's magnitude.
3. Fix the op *pattern*; leave the data alone if data wasn't the cost.
4. **Validate the fix against the pinned tool version before shipping**, and re-read the meter after deployment to confirm the drop.

**Worked example — Azure backup storage ([freeshard PR #106](https://github.com/FreeshardBase/freeshard/pull/106), June 2026).** On the shard-backup storage account, the top cost line was not stored data but the **"List and Create Container Operations" meter — roughly 3× the data-stored cost (~€15/mo), ~70% of the account's spend**. Attribution: `shard_core/service/backup.py` runs nightly `rclone sync` per shard per directory; without `--fast-list` rclone lists the destination hierarchically — one List Blobs op *per subdirectory* of a deep app-data tree (~3M ops/month fleet-wide); without `--azureblob-no-check-container` it also issued a redundant container check every invocation. Fix: add both flags; projected run-rate €41→~€26/mo. **The coda is half the lesson:** `--azureblob-no-check-container` did not exist in the rclone version pinned in the shipped image — core v18 rolled out and **all backups failed** ([#117](https://github.com/FreeshardBase/freeshard/issues/117), release blocker), fixed by dropping that flag in PR [#119](https://github.com/FreeshardBase/freeshard/pull/119) (commits d49f581, a4a80bc). As of 2026-07-03, `backup.py` on main carries `--fast-list` only. Any new rclone flag must be checked against the image's pinned rclone (`docker run --rm <image> rclone help flags | grep <flag>`), and whether the projected €26 run-rate materialized was still awaiting post-deploy meter confirmation.

**Failure mode of skipping it:** you optimize the 25% (data) and ignore the 70% (ops) — or, as #117 shows, you optimize the meter and take down the backup system, which costs more than the meter ever did.

---

## Recipe 8 — Hypothesis-predicts-numbers (run inside every recipe above)

**When:** always — before running any discriminating experiment or measurement. This is the discipline layer; freeshard-research-methodology covers the full evidence bar and idea lifecycle, this recipe is the operational core.

**Steps:**
1. State every live hypothesis.
2. For each, **write down the number or observation it predicts** for the experiment you're about to run — before running it. Concrete values, not directions: not "the timeout will be long" but "30 s pool timeout + overhead ≈ 45 s".
3. Run the experiment once. Compare against the pre-registered predictions. A hypothesis that predicted the number is proven against its rivals; one that "explains" the number only after seeing it proves nothing.
4. Prefer experiments whose hypotheses predict **different** numbers (discriminating) over ones where all hypotheses predict "some failure".

**Worked micro-examples from the recipes above:** [#89](https://github.com/FreeshardBase/freeshard/issues/89) — pool-exhaustion predicted failure at ~30 s + overhead and "simultaneous batch death"; observed: all uncached requests 500 together at ~45 s. Recipe 1 — "new-image ulimit" predicted `ulimit -n` = 1024 on failing shards and higher on survivors; measured exactly that (controller [#322](https://github.com/FreeshardBase/freeshard-controller/pull/322)). Recipe 5 — OOM predicted "crash stops after RAM resize", SIGABRT predicted "no change"; the resize produced no change. Contrast with the #267 double-encoding chase (Recipe 2), where a hypothesis was *fitted to* an observation post-hoc and cost two rounds of correction.

**Failure mode of skipping it:** every observation confirms whatever you already believed — post-hoc, all hypotheses fit. The Content-Type investigation generated two confident wrong root causes precisely in the phase where observations were being explained rather than predicted.

---

## When NOT to use this skill

- You have a symptom and want the fastest known triage path for it → **freeshard-debugging-playbook** (symptom→triage table, known traps with stories).
- You want what happened in a specific past investigation — timeline, dead ends, status → **freeshard-failure-archaeology**.
- You want the evidence bar, idea lifecycle, or how hunches become accepted results here → **freeshard-research-methodology** (this skill's Recipe 8 is its operational core, cross-referenced, not a replacement).
- You need to run measurements/scripts against a live shard or the repo → **freeshard-diagnostics-and-tooling** (the how-to-measure toolbox; this skill is the how-to-*reason* toolbox).
- You're classifying/gating/releasing a change → **freeshard-change-control**. Nothing in this skill authorizes skipping its gates; a proven root cause still ships through review.
- You need theory background (crypto, signatures, forwardAuth, rclone crypt) → **freeshard-domain-reference**.

## Provenance and maintenance

Written 2026-07-03. Primary sources (all public): GitHub issues/PRs in FreeshardBase/{freeshard, freeshard-controller, web-terminal, app-repository} as linked inline; repo files `shard_core/web/internal/call_backend.py`, `shard_core/web/internal/auth.py`, `shard_core/database/connection.py`, `shard_core/service/backup.py`; controller files `freeshard_controller/service/pricing.py`, `data/core-versions/v18/docker-compose.yml`; commits 167d779, 1e0e7c1, 868e690, fd1d05b, d49f581, e2071cf; live `docker run … version` measurements dated inline.

Drift-prone facts and how to re-verify each:

| Fact (as of 2026-07-03) | Re-verify with |
|---|---|
| Fleet traefik pin is v2.11 (latest core version v18) | `gh api repos/FreeshardBase/freeshard-controller/contents/freeshard-controller-backend/data/core-versions --jq '.[].name'` then grep the newest vN's `docker-compose.yml` for `traefik:` |
| traefik:v2.6 binary = go1.17.10; v2.11 = go1.25.x | `docker run --rm traefik:v2.6 version`, `docker run --rm traefik:v2.11 version` |
| DB pool `max_size=20, timeout=10` | `grep -n 'max_size\|timeout' shard_core/database/connection.py` |
| call_backend forwards Content-Type | `grep -n 'content-type' shard_core/web/internal/call_backend.py` |
| backup.py: `--fast-list` present, `--azureblob-no-check-container` absent | `grep -n 'fast-list\|no-check-container' shard_core/service/backup.py` (on origin/main, not a stale local branch) |
| Pricing formula `(base + gb*0.04)*1.5*1.19`, half-up `int(x*100+0.5)`; VM base XS 5.50 / S 11.00 / M 19.80 / L 51.00 / XL 102.00 | `gh api repos/FreeshardBase/freeshard-controller/contents/freeshard-controller-backend/freeshard_controller/service/pricing.py --jq .content \| base64 -d` |
| Diagnostics probes still lack ExitCode/OOMKilled (gap open) | `gh issue view 327 --repo FreeshardBase/freeshard-controller --json state,title` |
| #120 (OOM visibility) and #121 (no-interruption window) still open | `gh issue view 120 --repo FreeshardBase/freeshard --json state`; same for 121 |
| Traefik-v3 migration still parked (stay-on-v2 decision holds) | read closing comment: `gh pr view 112 --repo FreeshardBase/freeshard --json comments --jq '.comments[].body'` |
| Azure backup run-rate landed at ~€26/mo (was unconfirmed) | `az costmanagement query` (via the api-azure skill where available) on the shard-backup storage account, meter "List and Create Container Operations" |
