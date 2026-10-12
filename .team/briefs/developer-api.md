# Developer (API): Current context and conventions

**Last updated:** 2026-10-12 (s44 done, two open items)

See `developer.md` for base conventions.

## s44: Live spend meter, heartbeat, and health (round 1 done; 2 items open)

The runner measures every turn and keeps a heartbeat file fresh; Python has one health rule table; the dashboard shows live spend rate, health colour, flow-box stats, and alerts. Round 1 (code, UI tests) is done. **Open:**

1. **N1 (regression, urgent):** `pillText` with `heartbeat: null` lost the space before "on". Fix: restore space. Test (unit-tester): `pillText` with open `step-start` but no heartbeat gives `▶ <role> on <story> · …`.
2. **U1 (boot guard, round 2):** Node cannot load `index.html` to test its functions. Add: `if (!globalThis.AGILE_TEAM_NO_BOOT) boot().catch(…)` as the last statement (nothing else at top level touches network or DOM beyond what U2 stubs).

E2E tests (six checklist items: green→amber→red, SIGKILL, graceful stop, scope toggle, URL lines, coverage) belong to integration-tester.

Key modules: `live.py` (Meter, Pulse, Turn, heartbeat file), `health.py` (Rules, judge, age, model_note), dispatch (pulse lifecycle, interrupted), po_tools (chore context for wait), snapshot (turns tail, heartbeat, health). Config: `[health]` thresholds (beat_s=20, stale_s=90, amber_tool_s=180, amber_quiet_s=300, red_quiet_s=600).

See ADR-0032, design `agile-team/docs/design/s44.md` (decisions D1–D9, rules H1–H7, R0–R15, test checklist).
