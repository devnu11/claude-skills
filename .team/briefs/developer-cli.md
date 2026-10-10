# Developer (CLI): Current context and conventions

**Last updated:** 2026-10-10 (s23 done)

See `developer.md` for the base conventions.

## Context reduction: Read little, no connectors (s23)

Your session has no Claude.ai connectors. Reduce re-sent context by being strategic with reads:

- **Find before read:** Grep with `-n` and content mode to locate what you need, then `Read` with `offset` and `limit`.
- **Design is your contract:** Each story has `docs/design/<id>.md` with rules, exact signatures, and modules to change. Read source only for what the design leaves open.
- **Never double-read:** If you already read a file, use grep again instead of re-reading.
- **Run quietly:** Test commands with `-q -x --no-header` flags; keep only the failures.

See ADR-0011 for the context reduction strategy.

## CLI-specific context

**Team presents product in ready-made environment (s13):** New modules and changes:
- `presentation.py` (new): presentation directory structure, completeness check, sandbox copy, Proxy prompt section
- `gates.py`: `Verdict.RETURN` (moves back without counting round), e2e done gate checks presentation completeness
- `dispatch.py`: per-role setup (Integration Tester lays out presentation, Proxy receives copy), Proxy precondition returns on missing presentation
- `sandbox.py`: `Order` dataclass holds presentation source, `Preparer.prepare` copies before launching, Proxy read scope includes `.team/acceptance/**`
- `cli.py`, `git_ops.py`: init error handling outside git (no traceback, proper message)
- See ADR-0008 for the architecture.

**Clean halt on limits, crashes, SIGTERM (s8):** New modules and changes:
- `halt.py`: exception → `Halt` (kind, reason); `HALTS` and `LIMIT_PATTERNS` tables; `classify()` detector chain
- `dispatch.Runtime.halt_run()`: records first halt, saves status+reason, posts note
- `dispatch._step_failed()`: catches role-step exceptions, classifies limit vs. other errors
- `cli._halt_exit()`, `cli._finish()`: top-level halt handling
- `po_tools.PoRun._settle()`: skips settle when `runtime.halted_by` is set
- Partial edits after a halt are left uncommitted for the human and s9
- s9 will save interrupted step edits; s10 will record partial cost. This story only stops cleanly.
- See ADR-0007 for the data-driven strategy.

**Nested sandbox roots (s7):** The Customer Proxy reads customer docs and uses the installed CLI. Ensure CLI help and examples don't reference source code paths. Keep documentation output friendly to restricted sandboxes.

**Bash enforcement (s7):** Design CLI output and examples to avoid quoted comments or ambiguous shell constructs. The Proxy's check is conservative; when it blocks a legitimate command, refactor the example or workflow.
