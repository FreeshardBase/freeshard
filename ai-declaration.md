# AI Declaration — Freeshard

Freeshard is built by two people and a fleet of coding agents. This file states where AI is used and how far it goes, so nobody has to guess from the commit history.

Format follows the disclosure convention used by selfhosted@lemmy.world: each phase is rated Hint / Assisted / Pair / Generated.

| Phase | Level | What that means here |
|---|---|---|
| Design | Pair | Architecture and product decisions are made by the two humans, in conversation with agents. Specs are drafted jointly and a human approves the spec before any code is written. |
| Implementation | Generated | Most code in shard_core and the controller is written by headless agents working from triaged, specced issues — one fresh agent per issue, one pull request per issue. |
| Testing | Generated | Tests are written by the same agents, including integration tests that run against real containers in CI. |
| Documentation | Generated | Documentation, changelogs and the repository's own runbook libraries are agent-authored under a rule that every command, path and reference must be verified before it is written, then human-reviewed. |
| Review | Pair | Every pull request gets an agent self-review and, for larger changes, an adversarial review by a second, independent agent. Nothing merges without a human approving it. That gate has never been automated and will not be. |
| Deployment | Assisted | Releases and staged fleet rollouts are triggered and watched by a human, using tooling the agents built. |

## What a human always does

- Decides what gets built and in which order.
- Writes or approves the specification for anything non-trivial.
- Reviews and approves every pull request before it merges.
- Runs and watches every release.

## What this is not

- It is not unreviewed generated code shipped to production. Every change passes a human review gate.
- It is not an autonomous company. The agents have no authority over what gets built, what it costs, or what we promise anyone.
- It is not a marketing claim. It is a description of a workflow, and it is here because communities we take part in ask for it — and because anyone can check it against our public commit history.

Questions about any of this are welcome: contact@freeshard.net

Last updated: 2026-08-24
