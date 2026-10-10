# ADR-0008: Team presents the product in a ready-made environment

**Date:** 2026-10-10  
**Status:** Accepted  
**Deciders:** developer-cli, architect, code-reviewer, unit-tester, integration-tester, customer-proxy

## Context

The Customer Proxy judges the product as a customer would receive it, but was previously responsible for building its own test environment. This created three problems:

1. **The hook refused Proxy's git init** because the Proxy's sandbox only allows read-only git commands
2. **`agile-team init` crashed** when run outside a git repository
3. **The Proxy could not read and rewrite its acceptance report** across steps

Additionally, the team's e2e acceptance tests needed:
- For `cli` deliveries: a git-initialized workspace with sample state files (sprints, blocked messages, crash logs)
- For `dashboard` deliveries: the same plus run files (events, ledger, inbox, outbox) that show each feature in the live dashboard

The human's rule: "The integration-tester prepares the environment. The Customer Proxy never builds or repairs an environment."

## Decision

The runner enforces a three-layer handoff in code:

1. **Presentation structure (.team/run/presentation/\<story\>/)**
   - Created and wiped by the runner before each integration-tester e2e step
   - Contains: `PRESENTATION.md` (guide for customer), `workspace/` (ready-made project), and optional files (live-status.json, seed data)
   - Per-delivery-kind recipes define what the tester puts in it (`cli`, `dashboard`, `library`, etc.)

2. **e2e gate: presentation completeness check (E4–E5)**
   - When acceptance step exists, e2e `done` gate checks: `PRESENTATION.md` exists and non-blank, and (if applicable) workspace is non-empty
   - Incomplete presentation bounces to e2e with round increment
   - `presentation.missing(config, story) → str | None` is the single definition, used by both gate and Proxy precondition

3. **Proxy precondition: no-round return (E6)**
   - If presentation missing when Proxy step runs, story returns to e2e without counting a round
   - New verdict type: `RETURN` (vs bounce/changes_requested)
   - No sandbox prepared, nothing billed; gate event emitted with `verdict: "return"`
   - For s4, s5, s8 (legacy stories at acceptance): missing presentation triggers return, then integration-tester rebuilds and runs gate

4. **Sandbox handoff (E7–E9)**
   - Runner copies presentation to `<sandbox>/presentation/` after sandbox wipe, before prepare runs
   - Symlinks preserved (s7 guarantee: Proxy cannot escape via symlinks)
   - Proxy prompt includes "What the team presents" section with absolute path and PRESENTATION.md quoted in full
   - Proxy can Read/Grep/Glob `.team/acceptance/**` and Write its report (same file Read-before-Write constraint)

5. **Init outside git (E11)**
   - `agile-team init` (not `--detect`) outside a git repository prints error to stderr and exits 1
   - Message: `agile-team init: not a git repository: <repo>; run git init first`
   - No traceback, and no files created

## Consequences

**Positive:**
- Team controls what the Proxy receives; Proxy never has to debug its own setup
- e2e gate enforces presentation quality before acceptance
- Proxy can read and rewrite its own acceptance report; story is repeatable
- Live-run outputs (status, events) captured and presented as-is
- Clean error when init is attempted outside git (no confusion about traceback)
- Same pattern scales to other delivery kinds (harness, manual, library, web)

**Negative and mitigations:**
- Gate checks only that presentation *exists*, not that it is *correct* (Proxy judges correctness via `changes_requested`)
- Workspace needs machine's git identity for init's commit (same as team's own commits)
- Presentation dir wipes on every tester step (intended: each run presents fresh state, no accumulation)
- Runner's `prepare` command has no way to serve non-workspace presentation files for `web` kind (devops handles: recipe uses `{sandbox}/presentation/workspace`)

**Impact on related work:**
- s4 (Dashboard), s5 (Dashboard live UI), s8 (Clean halt): all move from backlog to acceptance once s13 merges; Proxy returns legacy stories to e2e (no round), tester rebuilds presentation with recipes, gate passes, Proxy accepts
- s9+ (Save partial edits): presentation location is separate from run state; no conflict
- Future deliveries (harness, manual, library, web): use PRESENTATIONS table and recipe pattern from design

## Design reference

- Story: `.team/stories/s13.md`
- Design: `agile-team/docs/design/s13.md` (rules E1–E11, PRESENTATIONS table, recipes per kind)
- Implementation: `agile-team/runner/agile_team/presentation.py` (new), changes to `gates.py`, `dispatch.py`, `sandbox.py`, `cli.py`, `git_ops.py`
- Tests: `tests/unit/test_presentation.py`, `tests/unit/test_gates.py` (E4, E6), `tests/unit/test_dispatch.py` (Proxy prompt)
- Review: `.team/reviews/s13.md` (non-blocking follow-ups noted, no defects)
