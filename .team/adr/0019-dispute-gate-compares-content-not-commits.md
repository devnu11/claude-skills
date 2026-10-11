# ADR-0019: Dispute gate compares content, not commits

**Date:** 2026-10-11 (s30 done)  
**Status:** Accepted  
**Deciders:** Developer-cli (s30 implement), Unit-tester (s30 tests), Code-reviewer, Customer-proxy (s30 review & acceptance), Product-owner (Scribe)

## Context

In s11, disputes were raised with a baseline of the HEAD commit when the dispute was raised. At the `tests` gate, the runner compared the disputed test file against that baseline using `git diff`.

Two bugs made this fail consistently:

1. **Unresolved path:** pytest prints test ids relative to `agile-team/runner/` (e.g., `tests/test_po_tools.py::…`), but `git diff` runs from the repo root where that path doesn't exist. Git reports "no change" for a missing path and exits with 0, so the gate always bounced.

2. **Stale baseline:** A commit is not a useful baseline for "has the test been fixed?" A fix that lands in the base commit (like s23's corrected tests already at commit 3522ae6) can never "change" again, so the dispute would bounce indefinitely.

In sprint 10, s23 hit the round cap at `tests` even though the disputed tests were corrected and the suite was green. The human advanced it by hand (as for s19). Related: s11 (disputes), s24 (tests gate with prior code), s27 (repeat escalation).

## Decision

### 1. Resolve paths at raise time (F1, F2)

When a developer raises a dispute, the runner resolves the test id's file path (the id up to `::`) to a single tracked file at the repo root. It uses `git ls-files` with both an exact match and a suffix pattern. If the file cannot be resolved (no match, multiple matches, or unreadable), the dispute is rejected with a clear `UNTRACKED` message and bounces back to `implement` as a ROLE-authored round.

### 2. Store content hash as baseline (F3)

The dispute stores the resolved file path and a fingerprint (content hash) of the working-tree file at the moment the dispute was raised. The fingerprint normalises away whitespace and comments, so cosmetic edits don't count.

### 3. Gate compares content hash, not commits (F4, F5)

At the `tests` gate, `Checks.dispute_settled(dispute)` compares the file's current content hash with the baseline:
- If hashes differ → the test changed → pass to `implement` (dispute cleared)
- If hashes match → the test hasn't changed → bounce to `tests` with exact reason
- If the file is now gone → consider it changed → pass
- If the dispute was raised before s30 (empty baseline) → pass with legacy marker
- If dispute is confirmed → pass without checking

### 4. New fingerprint module (F5)

`fingerprint.py` computes content hashes that ignore cosmetic differences:
- **Python files** (`.py`, `.pyi`): tokenize the file, strip `COMMENT` and `NL` tokens, render `INDENT`/`DEDENT`/`NEWLINE` by name, all other tokens by their string. This ignores indentation width, blank lines, spacing, and comments, but catches assertion changes, parameter rows, test renames, and string changes (including docstrings).
- **Other files:** collapse whitespace per line, drop empty lines and marker lines (by comment suffix: `#`, `//`, `--`, etc.), join with newlines.
- **Result:** SHA256 hex digest of the normalised text.

### 5. Failure reason includes the baseline (F6)

When the gate bounces (`UNCHANGED`), the reason names the test id, file, and first 12 hex digits of the baseline, so the tester can see what they must fix.

### 6. Repeat escalates, not caps (F7)

No new code. A second identical bounce at `tests` triggers s27's repeat escalation rule (`repeat = 2`), so the story escalates to the Manager after one counted round. With defaults (`round_cap = 3`) the round cap is never reached by this bounce alone.

### 7. New PO tool: `pass_tests` (F8–F11)

A story stuck at `tests` (open dispute, round cap, blocked, or repeated setback) with a green suite can be moved to the next step by the PO with `pass_tests(story, reason)`. The tool:
- Requires a reason (captures story context for the next brief)
- Checks that the story is actually stuck and at `tests`
- Runs the test suite (only when needed; expensive); refuses if suite is red
- Moves the story, clears disputes/rounds/holds/blocks, and sets the note
- Appends to `manager_due` for later review
- Emits a `tests-passed` event on the timeline

This covers both s23 (blocked after a runner fault) and s24 (open dispute on an unresolvable path, or at round cap).

### 8. Legacy disputes load safely (F12)

Disputes saved before s30 hold an old `base` (commit hash) and no `file`/`baseline`. The loader drops `base` and leaves `file` and `baseline` empty. At the gate, empty baseline passes with the `LEGACY_PASS` marker.

## Consequences

- **No more dispute loops:** Corrected tests that pass the suite now satisfy the gate.
- **Cheaper manual intervention:** The PO can move stuck stories without editing `state.json` by hand; the runner enforces green suite + reason.
- **Clearer feedback:** Failure reasons name the file and baseline hash so the tester knows what to fix.
- **Scope:** New `fingerprint.py` module (stdlib only: hashlib, tokenize, pathlib), changes to `gates.py`, `state.py`, `cli.py`, `events.py`, `po_tools.py`, and role files. The dashboard gains one `TIMELINE` row for `tests-passed` events. Tests cover all cases: real change, cosmetic change, no change, baseline taken at raise, failure reasons, and legacy disputes.
- **Coverage:** 99.63%, ruff clean, 140 tests in the s30 suite pass.

## Related decisions

- **ADR-0018 (s11):** Test disputes and rulings at any step. This decision replaces s11's T3 (baseline) and T6 (diff check) rules.
- **ADR-0014 (s27):** Escalate repeated setbacks. F7 (repeat escalation) applies here; s30 adds no new repeat logic.
- **ADR-0012 (s24):** Rework gate and hold clearing. Complements the `pass_tests` tool via the clear-and-forward pattern.

## Design rules reference

Complete rules (F1–F12) and test checklist in `agile-team/docs/design/s30.md`. Key modules and functions documented in "Changes by module" section.
