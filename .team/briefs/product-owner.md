# Product Owner: Current context and conventions

**Last updated:** 2026-10-10 (s13 done)

## Backlog and sprint management

Every story starts in the backlog (`sprint: null` in state.json). To move a story into active work:
- Use `start_sprint(goal, stories)` to open a new sprint with named stories
- Unknown story IDs are refused with guidance
- Only sprint stories can proceed past their opener step; backlog stories are refused with "add it to a sprint"
- Legacy `state.json` files load stories into the backlog automatically
- On resume after a story is done, check whether to start a new sprint with remaining work

## Team presents product in ready-made environment (s13)

The runner enforces the handoff in code. When a story reaches acceptance:

- **e2e gate (on tester's done):** Gate checks presentation completeness (PRESENTATION.md non-blank, workspace non-empty for applicable kinds). Incomplete → bounce to e2e with round +1.
- **Proxy precondition:** If presentation missing when Proxy step runs, story returns to e2e without counting a round (`status: "returned"`, `verdict: "return"` in gate event). No sandbox, no prepare, no query, nothing billed.
- **Copy to sandbox:** Runner copies presentation to `<sandbox>/presentation/` before prepare runs, so Proxy gets ready-made workspace and guide.
- **Proxy reads report:** Proxy can Read/Write `.team/acceptance/<story>.md` across steps (same file Read-before-Write constraint).

For s4, s5, s8 (legacy stories now at acceptance): missing presentation triggers return to e2e (no round), tester builds and runs gate, Proxy accepts.

## Design and enforcement decisions

- **Clean halt on limits, crashes, SIGTERM (s8):** Data-driven halt handling. `HALTS` table maps each halt kind to run status, relay note kind, exit code (75/70/143), and advice. `LIMIT_PATTERNS` table detects and extracts limit reason (reset time is copied from message, not computed). No code branches on halt kind outside these tables. First halt in a process wins and is re-asserted. Partial edits left uncommitted for inspection; s9 will save them as a commit. ADR-0007 documents the strategy. Review was 2 rounds; found and fixed two defects (D1: exit code suffix leaked into reason; D2: partial edits were settled and committed unconditionally).
- **Dashboard live UI (s5):** Vanilla JS + EventSource, Mermaid 11.4.1 from CDN (lazy-loaded), CSS tokens for themes, all snapshot strings escaped. Five ADRs (0002–0006) document the technical choices. Review was 4 rounds; found and fixed two defects (bad selector, unescaped strings) and sparse-data crash.
- **Nested forbidden roots (s7):** Proxy sandbox computes the deepest literal path segment before wildcards, not just the top-level directory. The Proxy can read customer docs even when they share a parent directory with source code.
- **Deny on any view (s7):** Proxy Bash checks in two views (shell continuations and comment-aware). A denial in any view blocks the command, even if others allow it. This over-approximation prevents false negatives at the cost of rare false positives.
- **Team presents product in ready-made environment (s13):** Integration Tester builds `.team/run/presentation/<story>/` with `PRESENTATION.md`, `workspace/`, and optional live-run outputs. e2e gate checks completeness. Proxy gets copy in sandbox. Presentation missing → return to e2e (no round, no cost). ADR-0008 documents the strategy.

## What the human needs to know

No roles edit `.team/adr/` or `.team/briefs/` except the Product Owner's end-of-step handoff. Backstop the linchpin roles (Unit Tester, Integration Tester, Customer Proxy) by reviewing their self-checks in their final handoffs.
