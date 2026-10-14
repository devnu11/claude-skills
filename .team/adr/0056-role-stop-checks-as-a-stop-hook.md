# ADR-0056: A role's mechanical checks run as an SDK Stop hook, in the same agent

Story: s126. Design: `agile-team/docs/design/s126.md`.

## Context

The gates run after a step ends. A failure then goes to a new agent, which has to
rebuild the context the old one already had. In the run the human measured,
that cost 31 test-failure bounces, 13 bounces for a missing `PRESENTATION.md`
and 4 lint bounces. Most of these are mechanical: the agent that caused them
could have fixed them in a minute. The Agent SDK already runs a `PreToolUse`
guard in-process for every role step. A `Stop` hook can refuse the end of a
query, and its reason text goes back to the same agent as feedback.

## Decision

- Every role step (`StepKind.ROLE`, `StepKind.GATE_FIX`) gets an in-process SDK
  `Stop` hook (`stop_checks.StopChecks`) beside the `PreToolUse` guard. The PO,
  boundary fixes and review fixes get none.
- What a stop checks is data. `STOP_CHECKS` maps a role (developer
  specialisations share `developer`) to checks. `EVERY_ROLE` (`handoff`, `lint`)
  comes first, and `SPECS` gives each check its stage and the story step it needs.
- The hook runs the **same gate functions** as the pipeline
  (`Pipeline.step_gate`, `Checks.presentation`), with the gate's stage swapped for
  the check's `stop.*` stage. There is no second copy of the gate logic, and
  changes to the gates (s125 pending tests, s35 uncovered set) carry over to it.
- Lint is fixed, not reported. The toolchain's file fixers run on the step's
  changed in-scope files, then its file linter. The commands are templates
  (`{root}`, `{files}`) in `[toolchain.files]`. A key the config does not set
  comes from the named preset (`[python.files]`). The fixes are committed with
  the step.
- Only failures the role can fix are refused. That means in-scope files, and
  for the suite, the `owners` split the gate's routing uses. Any non-`done`
  handoff stops at once with no checks. Every refusal ends with the way out
  (a `changes_requested` dispute).
- The hook is bounded. After 3 refusals per step, or once `[gates]
  stop_check_budget_s` is spent, the stop is allowed and the gate decides as
  before. The matcher's SDK timeout is set very high, so the runner's own
  bounds decide and the SDK never cancels a running suite.
- The implement gate reuses the hook's last suite run when the content is the
  same. `Git.content_digest(base)` hashes the working tree's content relative
  to the HEAD the hook ran on, so the step's commit does not change it.
- Each refused check writes a `stop-check` event. Stages opened inside an
  attempt carry `attempt: {n, of}`. The Flow chart shows stop checks as the
  role's after tool boxes, with `· n refused` and `attempt n of 3`.

## Consequences

- A step can take longer, because the developer's step now includes one full
  suite-and-coverage run (more if it is refused). The gate usually does not run
  it again, so the total suite time stays about the same, and bounces to a fresh
  agent drop.
- The model and tool time of a step now includes the hook's command time, which
  shows as a runner chore (`stop checks for …`).
- The Stop hook's input does not carry the final message, so the hook reads the
  text that `collect` has already taken (`Plan.said`). A rare race costs one
  refusal, which the cap bounds.
- `stop` is a built-in stage namespace, so `[[tool]]` names cannot use it.
- A repo on a preset without `files` (node, rust) gets no lint stop check until
  it configures `[toolchain.files]`.
- Role prompts must say what their stop checks, and that escalation is never
  blocked.
