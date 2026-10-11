# ADR-0024: Advance ruling, dispute output, and rework gate for code already in

**Decision:** Enable stories whose implementation is already in the branch to pass the tests gate, add an `advance` ruling that moves stories forward one step, capture dispute test output, and show it in briefs.

**Date:** 2026-10-11

## Context

Sprint 16 uncovered three problems that blocked the pipeline:

1. **Code in, test gate bounces (AC1):** s40's developer committed code at `implement` and raised a dispute. Once the dispute was cleared, the story was at `tests` with a green test suite. The tests gate bounced it twice: `tests pass before implementation; write a failing test`. The story's implementation was live in the branch, but the gate ignored it because `implemented == 0`. The s24 rework gate read only `implemented`, not whether commits were in git. No role could satisfy the gate; the Manager had to move the story by hand.

2. **No ruling moves a story forward (AC2):** The Manager has rulings (`rescope`, `upgrade_model`, `revise_design`, `escalate`), but none move a story past an unsatisfiable gate. `rescope` and `revise_design` move it back; `escalate` blocks it. The human had to edit state.json or git to move the story forward.

3. **Dispute brief names only the test (AC4):** The unit-tester received a dispute brief with the test id and reason, but not what failed. In s40, the named test was not failing. The tester rightly changed nothing, the gate bounced twice, and the dispute could not be cleared. The brief should quote the test output.

The fix requires:

- Recording code commits during every developer role step (K1).
- Checking whether recorded commits are ancestors of HEAD (K2).
- Using a rework gate at `tests` when code is in (K3).
- Adding an `advance` ruling that moves stories forward (A1).
- Capturing test output when a dispute is raised (D1).
- Showing dispute output in briefs while the dispute is open (D3).

## Decision

### Code commits and rework gate (AC1)

1. **Record commits (K1):** `StoryState.code_commits: list[str]` holds the sha of every commit the runner makes for a developer role's step, in any outcome (pass, bounce, dispute, review fix). `Runtime.commit_step` appends it. Nothing removes entries. Older state.json files load `[]` by default.

2. **Code is in (K2):** `Checks.code_in(story)` returns `True` when `story.implemented > 0`, or when any sha in `story.code_commits` is an ancestor of HEAD (via `git merge-base --is-ancestor <sha> HEAD` exit 0). It short-circuits: with `implemented > 0` or an empty list, no git command runs.

3. **Rework gate replaces red-gate logic (K3, K4):** `Pipeline.reworked(story)` is `story.step == "tests" and story.dispute is None and checks.code_in(story)`. The `_gate_for` method uses it in place of s24's `story.implemented` test. From there on, s24 G4/G6 apply unchanged: red suite passes, green suite passes with `"tests": "confirmed"` claim and bounces without one. A non-`done` handoff goes to `_handoff_outcome`. First-pass logic (K4) is unchanged: with `implemented == 0` and no recorded commits in the branch, `tests_red` runs exactly as before.

4. **Unit-tester brief (K5):** The prompt carries `REWORK_BRIEF` exactly when `Pipeline.reworked(story)` holds, so the brief and gate never disagree.

5. **Manager context (K6):** `repeated_setback` in the Manager's runner context gains `"code": {"implemented": <int>, "code_commits": [<shas in the branch>], "code_in": <bool>}`. `code_commits` lists only recorded shas that are ancestors of HEAD, in recorded order.

### Advance ruling (AC2)

1. **New ruling type (A1):** `roles.RULINGS` becomes `("rescope", "upgrade_model", "revise_design", "escalate", "advance")`. `advance` clears the story's loop (rounds, disputes, open dispute, streak, run, repeated, escalated_by), sets it `active`, then moves it **one enabled step forward** with `Pipeline._forward`. Moving forward from `implement` adds 1 to `implemented` (per s24 G1).

2. **Fault first, then advance (A2):** On the fault path (s45), the fault applies first, then the ruling. So `{"fault": "runner", "ruling": "advance"}` on a story stuck at `tests` blocks it, posts the runner-fault note to the human, then advances it to `implement` and sets it `active`.

3. **Advance cannot finish a story (A3):** At the last enabled step, `advance` is refused: `{"ruling": "advance", "applied": false, "why": "story {id} is at {step}, its last step; advance cannot mark it done"}`. The story does not change, and the PO gets the existing `ruling_not_applied` hand-over.

4. **Ruling reason in event (A4):** A handoff may carry `"ruling_reason": "<text>"` (string; defaults to `summary` when absent or empty, like dispute reasons). Every applied ruling's `ruling` event logs `{"ruling", "reason", "now_at"}`, where `reason` is `handoff.ruling_reason`. The Manager's report shows only `{"ruling", "applied", "now_at"}`, unchanged.

### Dispute output (AC4)

1. **Capture at raise (D1):** When a dispute opens (after its file resolves and baseline is taken, s30), the runner runs the `test` command once and stores `OpenDispute.output` (default `""`, so older disputes load without it).

2. **What is stored (D2):** Exit 0: `"the test command passes, so {test} is not failing"`. Non-zero: `excerpt(output, test_name(test))`, the output from the first line that contains the test name, up to 40 lines, followed by every later line that contains the name (pytest's `FAILED …::name - AssertionError` summary line). When no line contains the name: `"the test command fails, but its output never names {name}; its tail:\n<30-line tail>"`. `test_name(test)` is the part after the last `::` (or the whole id if no `::`).

3. **Dispute brief (D3):** While the dispute is open, the line after the T9 `Test dispute (…)` line is `"Output of the test command when the dispute was raised:\n\`\`\`\n{output}\n\`\`\`"`, only when `output` is not empty.

## Implementation

### Modules affected

- **`roles.py`:** `RULINGS` gains `"advance"`. `Handoff.ruling_reason: str = ""` field. HANDOFF_RULES validates it is a string.
- **`gates.py`:** `OpenDispute.output: str = ""`, after `stage`. `StoryState.code_commits: list[str] = field(default_factory=list)`, after `implemented`. Module functions `test_name(test: str) -> str` and `excerpt(output: str, name: str) -> str | None`. `Checks.landed(sha: str) -> bool`, `Checks.code_in(story) -> bool`, `Checks.code_facts(story) -> dict[str, Any]`, `Checks.test_output(test: str) -> str`. `Pipeline.reworked(story) -> bool`. `Pipeline._gate_for`: second branch becomes `if self.reworked(story): return self._rework_gate(handoff)`. `Pipeline._open`: when baseline exists, return `OpenDispute(..., output=self.checks.test_output(d.test))`. `Pipeline.apply_ruling` becomes: `_clear`, then status, then `_move_for(story, ruling)`. `Pipeline._move_for(story, ruling) -> None`: table routing each ruling type. `Pipeline.ruling_move_refusal(story, ruling) -> str | None`: refusal text for `advance` at last step, else `None`.
- **`dispatch.py`:** `DISPUTE_OUTPUT` constant. `commit_step` calls `_record_code(plan, sha)`. `_record_code(plan, sha) -> None`: appends sha when developer role at implement. `user_prompt`: calls `_story_lines(plan.story, self._rework_lines(plan.story))`. `Runtime._rework_lines(story: StoryState | None) -> list[str]`: returns `[REWORK_BRIEF]` when reworked, else `[]`. `_story_lines(story, rework)` builds the prompt with rework lines. `_dispute_lines` appends `DISPUTE_OUTPUT.format(output=d.output)` when `d.output`. `_repeated_context` adds `"code": code_facts(story)` to manager view. `_rulings` / `_rule_after_fault` pass `handoff` to `_rule`. `_rule(plan, handoff)` checks `ruling_move_refusal` refusal; ruling event emits `reason=handoff.ruling_reason`.
- **`loops.py`, `state.py`, `handover.py`, `router.py`:** No change.

### Exact strings (tests may assert them)

```python
# gates.py
ANCESTOR_COMMAND = "git merge-base --is-ancestor {sha} HEAD"
ADVANCE_LAST = "story {id} is at {step}, its last step; advance cannot mark it done"
EXCERPT_LINES = 40
TEST_GREEN = "the test command passes, so {test} is not failing"
TEST_NOT_IN_OUTPUT = "the test command fails, but its output never names {name}; its tail:\n{tail}"

# dispatch.py
DISPUTE_OUTPUT = "Output of the test command when the dispute was raised:\n```\n{output}\n```"
```

## Consequences

**Positive:**
- Stories with code already in the branch can now pass the tests gate, fixing the s40 loop.
- The Manager can move stuck stories forward with `advance`, unblocking pipelines that have no role to satisfy the gate.
- Dispute briefs now quote failing test output, letting the unit-tester and architect decide what to do based on facts, not just a test name.

**Tradeoffs:**
- `code_commits` is recorded for every developer step outcome, including bounces and disputes. This is intentional: commits exist regardless of outcome, and the git history is the source of truth.
- `advance` at the last step is refused. This prevents the ruling from finishing a story (acceptance stays with the Proxy or human).
- Dispute output capture runs the test command once at raise time. A flaky test might pass now and fail later when the dispute is cleared.

**Future:**
- Role files (`unit-tester.md`, `manager.md`) are updated in follow-up s54 to document `advance`, `ruling_reason`, and rework context for the Manager.
- Backfilling `code_commits` for old stories from the event log is out of scope; the Manager uses `advance` to move them.

## References

- Story: `.team/stories/s46.md`
- Design: `agile-team/docs/design/s46.md`
- ADR-0024: Advance ruling, dispute output, code already in (this ADR)
- ADR-0018: Test disputes and rulings at any step (s11)
- ADR-0019: Dispute gate compares content, not commits (s30)
- ADR-0012: Rework gate and hold clearing (s24)
