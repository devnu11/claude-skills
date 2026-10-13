# Developer (API): Current context and conventions

**Last updated:** 2026-10-12 (s59 done)

See `developer.md` for base conventions.

## s59: Rebase at sprint start (ADR-0041, round 3 done)

New module `agile_team/rewrite.py` (pure): pairs old-to-new commits by stamp (author, date, message) and rewrites hashes in `state.json`. Updated `upstream.py`: replaced `merge_in` with `rebase_onto` (uses `git rebase --empty=drop`, no `-s ours`). New `Rebase` class, `SyncOutcome` enum. `boundary_runner.py`: `_pin_sync_from` guard saves before rebase; `AFTER_REBASE` dispatch table handles outcomes. `handover.py`: conflict now groups files by directory. Dashboard tone: `rebased: "good"`. E2E tests (5 cases: all upstream, copies+new, real conflict, hash rewrite, hand rebase after conflict) pending for integration-tester.

**Defects fixed in round 3:** R2 save ordering (D1, D2), type hints and `_swap` helper (D4), test rename (D3).

See design `agile-team/docs/design/s59.md` (R1–R12, test checklist), review round 3.

## s74: Dashboard pill fixes — N1 text, resting stopped pill styling

Both open items from s44 are fixed. **N1:** `pillText` fallback branch now returns `` `▶ ${who(act)} · …` `` with a space after the arrow (was `▶${who(act)}`). **Resting pill:** Changed `STATUS_TONE.stopped` from `"warning"` to `""` (plain), so the run-status pill for `stopped` is not yellow. Extracted `statusPills(view, now)` to build pills as an array of HTML strings for unit testability. No changes to CSS, smart pill, health rules, or Python. See design `agile-team/docs/design/s74.md` (changes C1–C3, rules N1, S1–S3), ADR-0037.

## s44: Live spend meter, heartbeat, and health (all items complete)

The runner measures every turn and keeps a heartbeat file fresh; Python has one health rule table; the dashboard shows live spend rate, health colour, flow-box stats, and alerts. Round 1 (code, UI tests) is done. **Open:**

1. **N1 (regression, urgent):** `pillText` with `heartbeat: null` lost the space before "on". Fix: restore space. Test (unit-tester): `pillText` with open `step-start` but no heartbeat gives `▶ <role> on <story> · …`.
2. **U1 (boot guard, round 2):** Node cannot load `index.html` to test its functions. Add: `if (!globalThis.AGILE_TEAM_NO_BOOT) boot().catch(…)` as the last statement (nothing else at top level touches network or DOM beyond what U2 stubs).

E2E tests (six checklist items: green→amber→red, SIGKILL, graceful stop, scope toggle, URL lines, coverage) belong to integration-tester.

Key modules: `live.py` (Meter, Pulse, Turn, heartbeat file), `health.py` (Rules, judge, age, model_note), dispatch (pulse lifecycle, interrupted), po_tools (chore context for wait), snapshot (turns tail, heartbeat, health). Config: `[health]` thresholds (beat_s=20, stale_s=90, amber_tool_s=180, amber_quiet_s=300, red_quiet_s=600).

See ADR-0032, design `agile-team/docs/design/s44.md` (decisions D1–D9, rules H1–H7, R0–R15, test checklist).
