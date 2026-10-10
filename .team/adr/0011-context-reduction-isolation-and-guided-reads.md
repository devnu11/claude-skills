# ADR-0011: Context reduction — MCP isolation and guided reads for role steps

**Date:** 2026-10-10  
**Status:** Accepted  
**Story:** s23  
**Deciders:** developer-cli, architect, code-reviewer, unit-tester

## Context

While PO session cost grew across sprints, role steps had a different problem: large context per turn. Measurement of s19 (Unit Tester, 25 turns) found that re-sent context averaged 113.9k tokens per turn. The causes were clear:

| Cause | Share | Fix |
|-------|-------|-----|
| Claude.ai connectors loaded into every session (~43k per call) | 33% | Disable in `ISOLATION_ENV` |
| Whole-module `cat`s (42 KB cut to 2 KB preview, then re-read) | 35% | Brief on reading little; architecture → per-story designs |
| Design and story read on first call | 11% | Per-story designs already in brief |
| Writing and patching tests; test runs | 14% | Work lean guidance |

The root issue: every turn re-sends all previous reads, so early reads (full files, connector setup) cost the most. The fix required both code-level isolation (disable connectors) and behaviour change (read strategically).

## Decision

Three changes work together to reduce role context:

1. **MCP isolation** (L1, `dispatch.py`): All role steps and PO queries disable Claude.ai connectors (`ENABLE_CLAUDEAI_MCP_SERVERS=false`). The PO keeps its `team` server for `story_status` etc.; the Customer Proxy keeps its sandbox servers. This alone saves 33% per step (43k tokens).

2. **Architecture fragmentation** (L4, design files): Move designs out of the 1600-line `architecture.md` into focused per-story files (`docs/design/<id>.md`). Each design names exact signatures, import paths, and test checklist so Unit Testers and Developers read only what's needed.

3. **Role guidance** (L2, L3, `roles/*.md`):
   - **All roles** get "Read little": Find before you read (grep to locate, then read with offset/limit), never `cat` long files through Bash, read each file once, run checks quietly, use the brief's design file as contract.
   - **Unit Tester** gets "Work lean": Start from the design's test checklist, read only test helpers you reuse, write each test file in one go then fix with Edit, run only your files first (quiet, fail-fast), run the full suite once at the end with tail.

The Architect's brief adds: "Keep each design file focused: rules, changes per module with exact signatures and import paths, and a test checklist."

## Consequences

- **Isolation saves 33%:** No connector overhead in role steps (~43k tokens per turn gone).
- **Architecture clarity:** Per-story designs are easier to navigate and brief without the noise of 1600 unrelated lines.
- **Guided reads:** Explicit rules turn context awareness into practice. Roles learn to grep, offset-read, and avoid double-reads.
- **Measured improvement:** Unit Tester context per turn should drop under 60k (target from AC4). Baseline (s19): 113.9k.
- **Trade-off:** Roles without the connectors cannot use Claude.ai integrations during their step. This is acceptable because role steps are focused (design, implement, test, review) and don't need external tools.

## Implementation

- `dispatch.py` `ISOLATION_ENV` applies to `build_options` for every role plan and PO plan query.
- `roles/_shared.md` section "Read little" applies to all roles (inherited via `extends`).
- `roles/unit-tester.md` section "Work lean" adds Unit-Tester-specific practices.
- `roles/architect.md` deliverables remind architects to keep design files focused.
- `roles/manager.md` "Inputs" gains `long_running_roles` and "What to look for" monitors roles that exceed 30 turns in 2 of the last 3 measured steps.

## Related decisions

- **ADR-0010:** PO session renewal saves cost per sprint. This ADR reduces cost per step, per role.
- **ADR-0002:** Vanilla JS + EventSource for live updates; no connectors needed for the dashboard.
- **S19 ADR-0009:** Routing is code-driven; PO is lighter, so isolation affects the PO less (already brief).
