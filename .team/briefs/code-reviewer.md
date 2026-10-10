# Code Reviewer: Current context and conventions

**Last updated:** 2026-10-10 (s8 done)

## Design decisions to verify

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
