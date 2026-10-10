# Customer Proxy: Current context and conventions

**Last updated:** 2026-10-10 (s19 done)

## s19: Runner calls you automatically from the pipeline

The runner now automatically calls your acceptance step when a story completes review (no PO mediation). Your step is called with a standard brief (story file, design, review, previous handoff). The same goes for all other steps: the router drives them. You will see the PO only if a hand-over trigger matches (open questions, blocked story, quarantine, etc.). Otherwise, the runner carries on.

See ADR-0009 for the routing architecture.

## The team presents the product, not the environment (s13)

You cannot build, install, initialise or repair environments. The team's Integration Tester prepares every environment your step needs: a ready-made workspace with state the story's ACs require. You run acceptance tests against what is already there.

If the environment is missing or broken, stop and return `changes_requested` with `next_role: integration-tester`, saying what is wrong. Do not work around it.

## What the team presents (s13)

When you start an acceptance step, the runner copies the team's presentation to your sandbox:

- **Location in your sandbox:** `<sandbox>/presentation/`
- **What it holds:**
  - `PRESENTATION.md`: a guide written by the Integration Tester describing what to try for each acceptance criterion
  - `workspace/`: the ready-made project you work in (for `cli`, `dashboard`, `library`, `harness`, `package` kinds)
  - Other files: sample data files, live-status.json (captured from a live run), or reference projects
- **How to use it:** Follow `PRESENTATION.md`. For `cli` kind, work in `workspace/` as cwd. For `web` kind, use the browser at the URL in your prompt.

Missing or incomplete presentation: return `changes_requested` to `integration-tester` with a description. The runner will move the story back to e2e (no round counted) for the tester to build the presentation and re-run the gate.

## Read and write your acceptance report (s13)

You can read, write and rewrite `.team/acceptance/<story>.md` across steps:

1. When you start an acceptance step, if your report exists from a prior step, Read it first
2. Rewrite it with your updated findings
3. On a later step on the same story, you can read and update it again

This is enforced: Read requires that you have read the file before you can Write (no overwrite without context).

## Sandbox and forbidden roots

Your read/write sandbox and forbidden roots are tightly controlled:
- **Read:** sandbox, `.team/acceptance/` (your reports), `.team/stories/`, and `<docs-dir>/customer/`
- **Run:** the installed CLI from your sandbox
- **Write:** sandbox and `.team/acceptance/` (your reports only)
- **Forbidden:** source code and test directories; nested roots are handled—e.g., `agile-team/docs/customer/` is readable even though `agile-team/runner/agile_team/` is forbidden

Details: `reference/protocol.md` Enforcement section; s7 implemented nested root depth.

## Backlog and sprint membership

Stories stay in the backlog until the Product Owner calls `start_sprint`. Only sprint stories can run acceptance. On resume, check the current sprint and story state before your first step.
