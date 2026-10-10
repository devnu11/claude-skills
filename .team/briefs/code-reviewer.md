# Code Reviewer: Current context and conventions

**Last updated:** 2026-10-10 (s23 done)

## Design decisions to verify

**Routing in code — hand-over triggers as data (s19):** Verify that the router and hand-over logic are data-driven:
- `handover.HANDOVERS` table is the single source of truth for when to hand over (no branching outside it)
- Table rows match in order; when multiple rows match, all triggers are handed over
- `BRIEF_PATHS` table and `standard_brief()` apply the same logic to every step (story, design, review paths checked in order; previous/note lines added only when applicable)
- `ROLE_HINTS` tuple defines role selection order (R3); `step_role()` applies it and always finds a role (fallback to `developer`)
- `Router.PICKERS` tuple defines work order: Manager, Scribe, movable story (rule R2); `next_work()` returns the first non-None
- `Router.advance()` loop respects stop/halt at entry and after each turn; `_ended()` is the only halt check
- `_scribable()` allows unheld stories or `DONE` stories (D1 fix); R12 blocking by open questions still applies to done stories
- `note_step()` sets holds from the report's trigger names; `continue_story` refuses done stories (by design)
- Rules R1–R18 are well-covered by tests (design's test checklist section 7); verify coverage claim
- See ADR-0009 for the full strategy.

**Team presents product in ready-made environment (s13):** Verify that the handoff is enforced in code:
- `presentation.py` has single source-of-truth functions: `lay_out()` (wipes, creates workspace, git init), `missing()` (exact reason strings), `copy_into()` (symlinks preserved), `prompt_section()` (heading + path + guide)
- e2e `done` gate checks presentation completeness via `Pipeline._done_gate()` (only when acceptance step exists)
- Proxy precondition checks via `Pipeline.unpresented()` returns story to e2e with `Verdict.RETURN` (no round, no cost)
- Sandbox copy runs via `Preparer.prepare()` → `_copy_presentation()` after wipe, before prepare launch (E7 order)
- Proxy read globs and allowed reads add `.team/acceptance/**` and `<repo>/.team/acceptance` (report access)
- Proxy write scope unchanged: sandbox + `.team/acceptance/**`; `Read` added to `web`, `harness`, `manual` tools
- `git init` outside git: `Git.is_repo()` probes, `_require_init_inputs()` checks first, raises `CliError` with exact message (no traceback)
- Story id safety checked in `lay_out()` before wiping (refuses unsafe id with `SandboxError`)
- See ADR-0008 for the full strategy.

**Clean halt on limits, crashes, SIGTERM (s8):** Verify that halt handling is data-driven:
- `HALTS` table (kind → status, note_kind, exit_code, advice) with no code branches outside it
- `LIMIT_PATTERNS` table (regex, template) strips the SDK's ` (exit code: N)` suffix before matching; reset text copied from message, not computed
- `classify()` uses a detector chain (limit_halt, sigterm_halt, crash_halt); first non-None wins
- First halt recorded and re-asserted; later halts do not post a new note
- `_settle()` skipped when `runtime.halted_by` is set (partial edits left uncommitted)
- See ADR-0007 for the full strategy.

**HTML escaping in dashboard (s5):** Every `${…}` that places a snapshot field into HTML must be wrapped with either `esc()` (for HTML) or `mmdText()` (for Mermaid labels). Grep for suspicious patterns: `${ *[a-z.-]+\}[^)]`, `innerHTML *=.*\$`, unquoted attributes. See ADR-0005 for the rule and safe patterns. Exception: values from code, not snapshots (regex matches, map results of escaped strings).

**Mermaid graph edge selectors (s5):** Review that `findEdge(from, to)` queries SVG ids by prefix `L_<from>_<to>_` (Mermaid 11 convention, not v10's `LS-`/`LE-` classes). Round 1 defect D1 was this selector failing silently. Verify the fix and ask for a runtime test (headless Chrome) as a follow-up.

**Over-approximation in security (s7):** The Proxy Bash enforcement denies on any plausible view of a command (shell or comment interpretation). Review that this over-deny does not break legitimate workflows; ask the Customer Proxy to rephrase if it does.

**Backlog gating (s3):** Ensure the `_story_refusal` check is working: story-bound steps must refuse on backlog stories with a clear message.

**Test expectations (via Unit Tester):** The Unit Tester re-reads every test against the design. You are a secondary check for misalignments between code and tests.
